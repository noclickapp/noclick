"""
Google Search Console workflow node.
Pulls search performance data via the Search Analytics API, inspects URL indexing
status, and manages sitemaps for verified properties using OAuth credentials.
"""

import logging
import urllib.parse
from datetime import date, timedelta
from typing import Dict, Any, Optional, Union, Type, Literal, Annotated, List
from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import require_credential_token
from nodes.scopes.google_cloud import GOOGLE_SEARCH_CONSOLE_SCOPES

logger = logging.getLogger(__name__)

GSC_API_BASE = "https://www.googleapis.com/webmasters/v3"
# URL Inspection uses a different base than the rest of the GSC APIs
GSC_INSPECTION_API_BASE = "https://searchconsole.googleapis.com/v1"
GOOGLE_TOKENINFO_URL = "https://www.googleapis.com/oauth2/v3/tokeninfo"


def _gsc_raise_for_status(resp: httpx.Response) -> None:
    """Raise with Google's actual error message instead of the generic httpx one."""
    if resp.is_success:
        return
    try:
        body = resp.json()
        msg = body.get("error", {}).get("message") or resp.text
    except Exception:
        msg = resp.text
    if resp.status_code == 403:
        raise Exception(
            f"Google Search Console API error (403 Forbidden): {msg}\n"
            "This usually means either:\n"
            "  • The credential was connected without the 'webmasters' scope — reconnect via the Credentials tab\n"
            "  • The Google Search Console API is not enabled in the Google Cloud project"
        )
    raise Exception(f"Google Search Console API error ({resp.status_code}): {msg}")


def _gsc_int(value: Any) -> int:
    """GSC returns int64 counts (errors/warnings/submitted/indexed) as JSON strings."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ============================================================================
# Credential Schema
# ============================================================================


class GoogleSearchConsoleOAuthCredential(BaseModel):
    """OAuth credential for Google Search Console access."""

    credential_type: Literal["google_search_console_oauth"] = Field(
        "google_search_console_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Google"
    )
    refresh_token: str = Field(
        ...,
        title="Refresh Token",
        description="OAuth 2.0 refresh token for automatic renewal",
    )
    expires_at: str = Field(
        ...,
        title="Token Expiry",
        description="ISO 8601 timestamp when access token expires",
    )
    email: str = Field(
        ...,
        title="Google Account",
        description="Email address of the connected Google account",
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "google",
        "x-oauth-scopes": [
            "https://www.googleapis.com/auth/webmasters",
        ],
    })


# ============================================================================
# Configuration Models
# ============================================================================


class GoogleSearchConsoleQueryAnalyticsConfig(BaseModel):
    """Query search performance data: clicks, impressions, CTR, and position."""

    operation: Literal["query_search_analytics"] = Field(
        "query_search_analytics",
        json_schema_extra={
            "ui:hidden": True,
            "const": "query_search_analytics",
            "x-category": "Analytics",
            "x-is-trigger": False,
            "x-display-name": "Query Search Analytics",
        },
    )
    site_url: str = Field(
        ...,
        title="Site URL",
        description="Verified property (e.g. https://example.com/ or sc-domain:example.com)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "site_url",
                "placeholder": "Select a verified property...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter site URL",
            },
            "x-resource-type": "google_search_console_site",
        },
    )
    start_date: str = Field(
        "30daysAgo",
        title="Start Date",
        description="Start date in YYYY-MM-DD or relative format (today, yesterday, 30daysAgo)",
        json_schema_extra={"placeholder": "30daysAgo"},
    )
    end_date: str = Field(
        "yesterday",
        title="End Date",
        description="End date in YYYY-MM-DD or relative format (today, yesterday, 7daysAgo)",
        json_schema_extra={"placeholder": "yesterday"},
    )
    dimensions: str = Field(
        "query",
        title="Dimensions",
        description="Comma-separated dimensions: query, page, country, device, date, searchAppearance",
        json_schema_extra={"placeholder": "query, page, country"},
    )
    search_type: str = Field(
        "web",
        title="Search Type",
        description="Type of search results to include",
        json_schema_extra={
            "enum": ["web", "image", "video", "news", "discover", "googleNews"],
            "x-enum-searchable": False,
        },
    )
    row_limit: str = Field(
        "1000",
        title="Rows Per Page",
        description="Rows per API page (1–25000); large datasets are auto-paginated",
        json_schema_extra={"placeholder": "1000"},
    )
    max_rows: str = Field(
        "10000",
        title="Max Total Rows",
        description="Maximum total rows to return across all pages",
        json_schema_extra={"placeholder": "10000"},
    )
    filter_dimension: Optional[str] = Field(
        None,
        title="Filter Dimension",
        description="Dimension to filter by (e.g. country, query, page, device)",
        json_schema_extra={
            "placeholder": "country (optional)",
            "ui:category": "Filters",
        },
    )
    filter_operator: Optional[str] = Field(
        None,
        title="Filter Operator",
        description="Comparison operator for the filter",
        json_schema_extra={
            "enum": ["equals", "notEquals", "contains", "notContains", "includingRegex", "excludingRegex"],
            "x-enum-searchable": False,
            "ui:category": "Filters",
        },
    )
    filter_expression: Optional[str] = Field(
        None,
        title="Filter Value",
        description="Value to filter against (e.g. usa for country equals usa, MOBILE for device)",
        json_schema_extra={
            "placeholder": "usa (optional)",
            "ui:category": "Filters",
        },
    )
    data_state: str = Field(
        "final",
        title="Data State",
        description="Whether to include fresh but potentially partial data",
        json_schema_extra={
            "enum": ["final", "all"],
            "x-enum-searchable": False,
        },
    )


class GoogleSearchConsoleInspectUrlConfig(BaseModel):
    """Inspect indexing status, crawl state, and mobile usability for a URL."""

    operation: Literal["inspect_url"] = Field(
        "inspect_url",
        json_schema_extra={
            "ui:hidden": True,
            "const": "inspect_url",
            "x-category": "URL Inspection",
            "x-is-trigger": False,
            "x-display-name": "Inspect URL",
        },
    )
    site_url: str = Field(
        ...,
        title="Site URL",
        description="Verified property the inspected URL belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "site_url",
                "placeholder": "Select a verified property...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter site URL",
            },
            "x-resource-type": "google_search_console_site",
        },
    )
    inspection_url: str = Field(
        ...,
        title="URL to Inspect",
        description="Exact page URL to inspect (must belong to the selected site)",
        json_schema_extra={"placeholder": "https://example.com/blog/article"},
    )


class GoogleSearchConsoleListSitemapsConfig(BaseModel):
    """List all submitted sitemaps for a verified site with coverage statistics."""

    operation: Literal["list_sitemaps"] = Field(
        "list_sitemaps",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_sitemaps",
            "x-category": "Sitemaps",
            "x-is-trigger": False,
            "x-display-name": "List Sitemaps",
        },
    )
    site_url: str = Field(
        ...,
        title="Site URL",
        description="Verified property to list sitemaps for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "site_url",
                "placeholder": "Select a verified property...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter site URL",
            },
            "x-resource-type": "google_search_console_site",
        },
    )


class GoogleSearchConsoleSubmitSitemapConfig(BaseModel):
    """Submit or re-submit a sitemap URL to Google Search Console."""

    operation: Literal["submit_sitemap"] = Field(
        "submit_sitemap",
        json_schema_extra={
            "ui:hidden": True,
            "const": "submit_sitemap",
            "x-category": "Sitemaps",
            "x-is-trigger": False,
            "x-display-name": "Submit Sitemap",
        },
    )
    site_url: str = Field(
        ...,
        title="Site URL",
        description="Verified property to submit the sitemap for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "site_url",
                "placeholder": "Select a verified property...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter site URL",
            },
            "x-resource-type": "google_search_console_site",
        },
    )
    sitemap_url: str = Field(
        ...,
        title="Sitemap URL",
        description="Full URL of the sitemap to submit (e.g. https://example.com/sitemap.xml)",
        json_schema_extra={"placeholder": "https://example.com/sitemap.xml"},
    )


class GoogleSearchConsoleListSitesConfig(BaseModel):
    """List all verified Google Search Console properties for the account."""

    operation: Literal["list_sites"] = Field(
        "list_sites",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_sites",
            "x-category": "Sites",
            "x-is-trigger": False,
            "x-display-name": "List Sites",
        },
    )


class GoogleSearchConsoleGetSiteConfig(BaseModel):
    """Get permission level and details for a specific verified property."""

    operation: Literal["get_site"] = Field(
        "get_site",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_site",
            "x-category": "Sites",
            "x-is-trigger": False,
            "x-display-name": "Get Site",
        },
    )
    site_url: str = Field(
        ...,
        title="Site URL",
        description="Property URL to look up (e.g. https://example.com/ or sc-domain:example.com)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "site_url",
                "placeholder": "Select a verified property...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter site URL",
            },
            "x-resource-type": "google_search_console_site",
        },
    )


class GoogleSearchConsoleAddSiteConfig(BaseModel):
    """Add a new property to Google Search Console."""

    operation: Literal["add_site"] = Field(
        "add_site",
        json_schema_extra={
            "ui:hidden": True,
            "const": "add_site",
            "x-category": "Sites",
            "x-is-trigger": False,
            "x-display-name": "Add Site",
            "x-creates-resource": True,
            "x-resource-type": "google_search_console_site",
            "x-resource-id-path": "site_url",
        },
    )
    site_url: str = Field(
        ...,
        title="Site URL",
        description="Property to add — use https://example.com/ for URL-prefix or sc-domain:example.com for domain property",
        json_schema_extra={"placeholder": "https://example.com/"},
    )


class GoogleSearchConsoleDeleteSiteConfig(BaseModel):
    """Remove a property from your Google Search Console account."""

    operation: Literal["delete_site"] = Field(
        "delete_site",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_site",
            "x-category": "Sites",
            "x-is-trigger": False,
            "x-display-name": "Delete Site",
        },
    )
    site_url: str = Field(
        ...,
        title="Site URL",
        description="Property to remove from your Search Console account",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "site_url",
                "placeholder": "Select a verified property...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter site URL",
            },
            "x-resource-type": "google_search_console_site",
        },
    )


class GoogleSearchConsoleGetSitemapConfig(BaseModel):
    """Get submission status, error counts, and URL coverage for a specific sitemap."""

    operation: Literal["get_sitemap"] = Field(
        "get_sitemap",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_sitemap",
            "x-category": "Sitemaps",
            "x-is-trigger": False,
            "x-display-name": "Get Sitemap",
        },
    )
    site_url: str = Field(
        ...,
        title="Site URL",
        description="Verified property the sitemap belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "site_url",
                "placeholder": "Select a verified property...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter site URL",
            },
            "x-resource-type": "google_search_console_site",
        },
    )
    sitemap_url: str = Field(
        ...,
        title="Sitemap URL",
        description="Full URL of the sitemap to retrieve details for",
        json_schema_extra={"placeholder": "https://example.com/sitemap.xml"},
    )


class GoogleSearchConsoleDeleteSitemapConfig(BaseModel):
    """Remove a sitemap from the Sitemaps report in Google Search Console."""

    operation: Literal["delete_sitemap"] = Field(
        "delete_sitemap",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_sitemap",
            "x-category": "Sitemaps",
            "x-is-trigger": False,
            "x-display-name": "Delete Sitemap",
        },
    )
    site_url: str = Field(
        ...,
        title="Site URL",
        description="Verified property the sitemap belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "site_url",
                "placeholder": "Select a verified property...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter site URL",
            },
            "x-resource-type": "google_search_console_site",
        },
    )
    sitemap_url: str = Field(
        ...,
        title="Sitemap URL",
        description="Full URL of the sitemap to remove from Search Console",
        json_schema_extra={"placeholder": "https://example.com/sitemap.xml"},
    )


class GoogleSearchConsoleMobileFriendlyTestConfig(BaseModel):
    """Run Google's Mobile-Friendly Test on any public URL — no verified property required."""

    operation: Literal["mobile_friendly_test"] = Field(
        "mobile_friendly_test",
        json_schema_extra={
            "ui:hidden": True,
            "const": "mobile_friendly_test",
            "x-category": "URL Testing",
            "x-is-trigger": False,
            "x-display-name": "Mobile Friendly Test",
        },
    )
    url: str = Field(
        ...,
        title="URL",
        description="Public URL to test for mobile usability",
        json_schema_extra={"placeholder": "https://example.com/page"},
    )
    request_screenshot: str = Field(
        "false",
        title="Include Screenshot",
        description="Whether to include a rendered screenshot of the page in the response",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": False,
        },
    )


GoogleSearchConsoleConfig = Annotated[
    Union[
        GoogleSearchConsoleQueryAnalyticsConfig,
        GoogleSearchConsoleInspectUrlConfig,
        GoogleSearchConsoleListSitemapsConfig,
        GoogleSearchConsoleSubmitSitemapConfig,
        GoogleSearchConsoleDeleteSitemapConfig,
        GoogleSearchConsoleGetSitemapConfig,
        GoogleSearchConsoleListSitesConfig,
        GoogleSearchConsoleGetSiteConfig,
        GoogleSearchConsoleAddSiteConfig,
        GoogleSearchConsoleDeleteSiteConfig,
        GoogleSearchConsoleMobileFriendlyTestConfig,
    ],
    Discriminator("operation"),
]


class GoogleSearchConsoleNodeConfig(
    NodeConfig[GoogleSearchConsoleConfig, GoogleSearchConsoleOAuthCredential]
):
    pass


# ============================================================================
# Node Implementation
# ============================================================================


class GoogleSearchConsoleNode(WorkflowNode):
    edit_examples = [
        "Get top 100 queries for my site over the last 30 days ranked by impressions",
        "Pull search performance by page to find high-impression but low-CTR pages",
        "Check if my homepage is indexed and what Google uses as the canonical URL",
        "Get search analytics by country to see geographic traffic distribution",
        "List all sitemaps and compare submitted vs indexed page counts",
        "Submit updated sitemap after publishing new content",
        "Get performance by device type to compare mobile vs desktop CTR and position",
        "List all verified Search Console properties in the account",
        "Get permission level for a specific Search Console property",
        "Add a new domain property to Search Console",
        "Remove an old property from Search Console",
        "Get submission status and URL counts for a specific sitemap",
        "Delete an outdated sitemap from the Sitemaps report",
        "Run a mobile-friendly test on a landing page before launch",
    ]

    scope_registry = GOOGLE_SEARCH_CONSOLE_SCOPES
    connection_evidence = ConnectionEvidence(
        field="site_url",
        noun="verified properties",
    )

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        return GoogleSearchConsoleNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name == "site_url":
            return await cls._list_site_options(credential_data, search=search)
        return {"options": [], "next_page_token": None}

    @classmethod
    async def _list_site_options(
        cls,
        credential_data: Dict[str, Any],
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        access_token = require_credential_token(
            credential_data.get("access_token"),
            "Connect a Google account to load Search Console properties",
        )

        # Verify the token has the webmasters scope before hitting the API.
        # A missing scope is the most common cause of 403 on this endpoint.
        async with httpx.AsyncClient() as client:
            ti = await client.get(
                GOOGLE_TOKENINFO_URL,
                params={"access_token": access_token},
                timeout=10,
            )
            if ti.is_success:
                scope_str = ti.json().get("scope", "")
                if "webmasters" not in scope_str:
                    raise Exception(
                        "The connected credential does not have the Google Search Console (webmasters) permission. "
                        "Please disconnect the credential and reconnect it via the Credentials tab to grant the required access."
                    )

            resp = await client.get(
                f"{GSC_API_BASE}/sites",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30,
            )
            _gsc_raise_for_status(resp)
            data = resp.json()

        options = [
            {"label": entry.get("siteUrl", ""), "value": entry.get("siteUrl", "")}
            for entry in (data.get("siteEntry") or [])
        ]
        if search:
            q = search.lower()
            options = [o for o in options if q in o["label"].lower()]
        return {"options": options, "next_page_token": None}

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="google",
        )

    async def _ensure_fresh_token(self, credentials) -> str:
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.google_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="google",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        node_config = self.config
        config = node_config.config
        credentials = node_config.credentials

        if not credentials:
            return {"error": "No Google Search Console credentials configured"}

        access_token = await self._ensure_fresh_token(credentials)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        if config.operation == "query_search_analytics":
            return await self._query_search_analytics(config, headers)
        elif config.operation == "inspect_url":
            return await self._inspect_url(config, headers)
        elif config.operation == "list_sitemaps":
            return await self._list_sitemaps(config, headers)
        elif config.operation == "submit_sitemap":
            return await self._submit_sitemap(config, headers)
        elif config.operation == "delete_sitemap":
            return await self._delete_sitemap(config, headers)
        elif config.operation == "get_sitemap":
            return await self._get_sitemap(config, headers)
        elif config.operation == "list_sites":
            return await self._list_sites(headers)
        elif config.operation == "get_site":
            return await self._get_site(config, headers)
        elif config.operation == "add_site":
            return await self._add_site(config, headers)
        elif config.operation == "delete_site":
            return await self._delete_site(config, headers)
        elif config.operation == "mobile_friendly_test":
            return await self._mobile_friendly_test(config, headers)

        return {"error": f"Unknown operation: {config.operation}"}

    async def _query_search_analytics(
        self, config: GoogleSearchConsoleQueryAnalyticsConfig, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        site_encoded = urllib.parse.quote(config.site_url, safe="")
        dimensions = [d.strip() for d in config.dimensions.split(",") if d.strip()]
        row_limit = min(int(config.row_limit or 1000), 25000)
        max_rows = int(config.max_rows or 10000)

        start_date = _resolve_relative_date(config.start_date)
        end_date = _resolve_relative_date(config.end_date)

        payload: Dict[str, Any] = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": dimensions,
            "type": config.search_type or "web",
            "rowLimit": row_limit,
            "dataState": config.data_state or "final",
        }

        # Apply a single dimension filter if all three filter fields are set
        if config.filter_dimension and config.filter_operator and config.filter_expression:
            payload["dimensionFilterGroups"] = [{
                "groupType": "and",
                "filters": [{
                    "dimension": config.filter_dimension,
                    "operator": config.filter_operator,
                    "expression": config.filter_expression,
                }],
            }]

        all_rows: List[Dict[str, Any]] = []
        start_row = 0

        async with httpx.AsyncClient() as client:
            while len(all_rows) < max_rows:
                payload["startRow"] = start_row
                resp = await client.post(
                    f"{GSC_API_BASE}/sites/{site_encoded}/searchAnalytics/query",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
                _gsc_raise_for_status(resp)
                batch: List[Dict[str, Any]] = resp.json().get("rows") or []

                for row in batch:
                    keys = row.get("keys", [])
                    entry: Dict[str, Any] = {
                        dim: keys[i]
                        for i, dim in enumerate(dimensions)
                        if i < len(keys)
                    }
                    entry["clicks"] = int(row.get("clicks", 0))
                    entry["impressions"] = int(row.get("impressions", 0))
                    entry["ctr"] = round(row.get("ctr", 0) * 100, 2)  # convert to %
                    entry["position"] = round(row.get("position", 0), 1)
                    all_rows.append(entry)

                if len(batch) < row_limit:
                    break
                start_row += row_limit

        return {
            "site_url": config.site_url,
            "start_date": start_date,
            "end_date": end_date,
            "dimensions": dimensions,
            "search_type": config.search_type,
            "row_count": len(all_rows),
            "rows": all_rows[:max_rows],
        }

    async def _inspect_url(
        self, config: GoogleSearchConsoleInspectUrlConfig, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GSC_INSPECTION_API_BASE}/urlInspection/index:inspect",
                headers=headers,
                json={"inspectionUrl": config.inspection_url, "siteUrl": config.site_url},
                timeout=30,
            )
            _gsc_raise_for_status(resp)
            data = resp.json()

        result = data.get("inspectionResult", {})
        index_status = result.get("indexStatusResult", {})
        mobile = result.get("mobileUsabilityResult", {})
        rich_results = result.get("richResultsResult", {})

        return {
            "inspection_url": config.inspection_url,
            "verdict": index_status.get("verdict"),
            "coverage_state": index_status.get("coverageState"),
            "indexing_state": index_status.get("indexingState"),
            "robots_txt_state": index_status.get("robotsTxtState"),
            "last_crawl_time": index_status.get("lastCrawlTime"),
            "crawled_as": index_status.get("crawledAs"),
            "page_fetch_state": index_status.get("pageFetchState"),
            "google_canonical": index_status.get("googleCanonical"),
            "user_canonical": index_status.get("userCanonical"),
            "sitemaps": index_status.get("sitemap", []),
            "mobile_usability": mobile.get("verdict"),
            "rich_results": rich_results.get("verdict"),
            "inspection_result_link": result.get("inspectionResultLink"),
        }

    async def _list_sitemaps(
        self, config: GoogleSearchConsoleListSitemapsConfig, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        site_encoded = urllib.parse.quote(config.site_url, safe="")
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GSC_API_BASE}/sites/{site_encoded}/sitemaps",
                headers=headers,
                timeout=30,
            )
            _gsc_raise_for_status(resp)
            data = resp.json()

        sitemaps = []
        for sm in (data.get("sitemap") or []):
            contents = sm.get("contents") or []
            sitemaps.append({
                "path": sm.get("path"),
                "last_submitted": sm.get("lastSubmitted"),
                "last_downloaded": sm.get("lastDownloaded"),
                "type": sm.get("type"),
                "is_sitemaps_index": sm.get("isSitemapsIndex", False),
                "errors": _gsc_int(sm.get("errors")),
                "warnings": _gsc_int(sm.get("warnings")),
                "submitted_urls": sum(_gsc_int(c.get("submitted")) for c in contents),
                "indexed_urls": sum(_gsc_int(c.get("indexed")) for c in contents),
            })

        return {
            "site_url": config.site_url,
            "sitemap_count": len(sitemaps),
            "sitemaps": sitemaps,
        }

    async def _submit_sitemap(
        self, config: GoogleSearchConsoleSubmitSitemapConfig, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        site_encoded = urllib.parse.quote(config.site_url, safe="")
        sitemap_encoded = urllib.parse.quote(config.sitemap_url, safe="")
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{GSC_API_BASE}/sites/{site_encoded}/sitemaps/{sitemap_encoded}",
                headers={"Authorization": headers["Authorization"]},
                timeout=30,
            )
            _gsc_raise_for_status(resp)

        return {
            "status": "submitted",
            "site_url": config.site_url,
            "sitemap_url": config.sitemap_url,
        }

    async def _list_sites(self, headers: Dict[str, str]) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GSC_API_BASE}/sites",
                headers=headers,
                timeout=30,
            )
            _gsc_raise_for_status(resp)
            data = resp.json()

        sites = [
            {
                "site_url": entry.get("siteUrl"),
                "permission_level": entry.get("permissionLevel"),
            }
            for entry in (data.get("siteEntry") or [])
        ]

        return {
            "site_count": len(sites),
            "sites": sites,
        }

    async def _get_site(
        self, config: GoogleSearchConsoleGetSiteConfig, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        site_encoded = urllib.parse.quote(config.site_url, safe="")
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GSC_API_BASE}/sites/{site_encoded}",
                headers=headers,
                timeout=30,
            )
            _gsc_raise_for_status(resp)
            data = resp.json()

        return {
            "site_url": data.get("siteUrl"),
            "permission_level": data.get("permissionLevel"),
        }

    async def _add_site(
        self, config: GoogleSearchConsoleAddSiteConfig, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        site_encoded = urllib.parse.quote(config.site_url, safe="")
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{GSC_API_BASE}/sites/{site_encoded}",
                headers={"Authorization": headers["Authorization"]},
                timeout=30,
            )
            _gsc_raise_for_status(resp)

        return {
            "status": "added",
            "site_url": config.site_url,
        }

    async def _delete_site(
        self, config: GoogleSearchConsoleDeleteSiteConfig, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        site_encoded = urllib.parse.quote(config.site_url, safe="")
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{GSC_API_BASE}/sites/{site_encoded}",
                headers={"Authorization": headers["Authorization"]},
                timeout=30,
            )
            _gsc_raise_for_status(resp)

        return {
            "status": "deleted",
            "site_url": config.site_url,
        }

    async def _get_sitemap(
        self, config: GoogleSearchConsoleGetSitemapConfig, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        site_encoded = urllib.parse.quote(config.site_url, safe="")
        sitemap_encoded = urllib.parse.quote(config.sitemap_url, safe="")
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GSC_API_BASE}/sites/{site_encoded}/sitemaps/{sitemap_encoded}",
                headers=headers,
                timeout=30,
            )
            _gsc_raise_for_status(resp)
            sm = resp.json()

        contents = sm.get("contents") or []
        return {
            "path": sm.get("path"),
            "last_submitted": sm.get("lastSubmitted"),
            "last_downloaded": sm.get("lastDownloaded"),
            "type": sm.get("type"),
            "is_sitemaps_index": sm.get("isSitemapsIndex", False),
            "errors": _gsc_int(sm.get("errors")),
            "warnings": _gsc_int(sm.get("warnings")),
            "submitted_urls": sum(_gsc_int(c.get("submitted")) for c in contents),
            "indexed_urls": sum(_gsc_int(c.get("indexed")) for c in contents),
            "contents": contents,
        }

    async def _delete_sitemap(
        self, config: GoogleSearchConsoleDeleteSitemapConfig, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        site_encoded = urllib.parse.quote(config.site_url, safe="")
        sitemap_encoded = urllib.parse.quote(config.sitemap_url, safe="")
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{GSC_API_BASE}/sites/{site_encoded}/sitemaps/{sitemap_encoded}",
                headers={"Authorization": headers["Authorization"]},
                timeout=30,
            )
            _gsc_raise_for_status(resp)

        return {
            "status": "deleted",
            "site_url": config.site_url,
            "sitemap_url": config.sitemap_url,
        }

    async def _mobile_friendly_test(
        self, config: GoogleSearchConsoleMobileFriendlyTestConfig, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "url": config.url,
            "requestScreenshot": config.request_screenshot == "true",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GSC_INSPECTION_API_BASE}/urlTestingTools/mobileFriendlyTest:run",
                headers=headers,
                json=payload,
                timeout=60,
            )
            _gsc_raise_for_status(resp)
            data = resp.json()

        issues = [
            {"rule": issue.get("rule"), "message": issue.get("message")}
            for issue in (data.get("mobileFriendlinessIssues") or [])
        ]
        result: Dict[str, Any] = {
            "url": config.url,
            "mobile_friendliness": data.get("mobileFriendliness"),
            "issue_count": len(issues),
            "issues": issues,
        }
        if data.get("screenshot"):
            result["screenshot_mime_type"] = data["screenshot"].get("mimeType")
            result["screenshot_data"] = data["screenshot"].get("data")
        return result


def _resolve_relative_date(date_str: str) -> str:
    """Convert relative date strings (today, yesterday, NdaysAgo) to YYYY-MM-DD.

    GSC API requires absolute dates; GA4 handles relative strings server-side but GSC does not.
    """
    s = date_str.strip()
    if s == "today":
        return date.today().isoformat()
    if s == "yesterday":
        return (date.today() - timedelta(days=1)).isoformat()
    if s.endswith("daysAgo"):
        try:
            n = int(s[: -len("daysAgo")])
            return (date.today() - timedelta(days=n)).isoformat()
        except ValueError:
            pass
    return s
