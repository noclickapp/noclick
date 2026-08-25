"""
Google Analytics 4 (GA4) workflow node implementation.
Pulls analytics data via the GA4 Data API and Admin API using OAuth credentials.

Supports operations: run_report, run_realtime_report, get_metadata.
"""

import json
import logging
from typing import Dict, Any, Optional, Tuple, Union, Type, List, Literal, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import load_paginated_options, require_credential_token
from nodes.oauth.google_oauth import is_token_expired, refresh_access_token
from nodes.scopes.google_cloud import GOOGLE_ANALYTICS_SCOPES

logger = logging.getLogger(__name__)

GA4_DATA_API_BASE = "https://analyticsdata.googleapis.com/v1beta"
GA4_ADMIN_API_BASE = "https://analyticsadmin.googleapis.com/v1beta"


# ============================================================================
# Credential Schema
# ============================================================================


class GoogleAnalyticsOAuthCredential(BaseModel):
    """OAuth credential for Google Analytics 4 access."""

    credential_type: Literal["google_analytics_oauth"] = Field(
        "google_analytics_oauth", json_schema_extra={"ui:hidden": True}
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
            "https://www.googleapis.com/auth/analytics.readonly",
        ],
    })


# ============================================================================
# Configuration Models
# ============================================================================


class GoogleAnalyticsRunReportConfig(BaseModel):
    """Run a standard GA4 report with dimensions, metrics, date range, and optional filters."""

    operation: Literal["run_ga4_standard_report"] = Field(
        "run_ga4_standard_report",
        title="Run Ga4 Standard Report",
        description="Run a GA4 report",
        json_schema_extra={
            "ui:hidden": True,
            "const": "run_ga4_standard_report",
            "x-category": "Report",
            "x-is-trigger": False,
            "x-display-name": "Run Ga4 Standard Report",
        },
    )
    property_id: str = Field(
        ...,
        title="Property ID",
        description="GA4 property ID (numeric, e.g. 123456789)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "property_id",
                "placeholder": "Select a GA4 property...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter property ID",
            },
            "x-resource-type": "google_analytics_property",
        },
    )
    start_date: str = Field(
        "30daysAgo",
        title="Start Date",
        description="Start date (YYYY-MM-DD or relative: today, yesterday, NdaysAgo)",
        json_schema_extra={"placeholder": "30daysAgo"},
    )
    end_date: str = Field(
        "today",
        title="End Date",
        description="End date (YYYY-MM-DD or relative: today, yesterday, NdaysAgo)",
        json_schema_extra={"placeholder": "today"},
    )
    compare_start_date: Optional[str] = Field(
        None,
        title="Comparison Start Date",
        description="Optional comparison period start date (for month-over-month, year-over-year)",
        json_schema_extra={
            "placeholder": "60daysAgo (optional)",
            "ui:category": "Comparison",
        },
    )
    compare_end_date: Optional[str] = Field(
        None,
        title="Comparison End Date",
        description="Optional comparison period end date",
        json_schema_extra={
            "placeholder": "31daysAgo (optional)",
            "ui:category": "Comparison",
        },
    )
    dimensions: str = Field(
        "date",
        title="Dimensions",
        description="Comma-separated dimension names (e.g. date, city, pagePath, sessionSource, sessionMedium)",
        json_schema_extra={"placeholder": "date, sessionSource, sessionMedium"},
    )
    metrics: str = Field(
        "sessions,totalUsers,screenPageViews,conversions,engagementRate",
        title="Metrics",
        description="Comma-separated metric names (e.g. sessions, totalUsers, screenPageViews, conversions, engagementRate, bounceRate)",
        json_schema_extra={
            "placeholder": "sessions, totalUsers, screenPageViews, conversions"
        },
    )
    dimension_filter: Optional[str] = Field(
        None,
        title="Dimension Filter",
        description='Filter dimensions as JSON (e.g. {"fieldName": "country", "stringFilter": {"value": "US"}})',
        json_schema_extra={
            "placeholder": "Optional JSON filter",
            "ui:category": "Filters",
        },
    )
    metric_filter: Optional[str] = Field(
        None,
        title="Metric Filter",
        description='Filter metrics as JSON (e.g. {"fieldName": "sessions", "numericFilter": {"operation": "GREATER_THAN", "value": {"int64Value": "100"}}})',
        json_schema_extra={
            "placeholder": "Optional JSON filter",
            "ui:category": "Filters",
        },
    )
    limit: str = Field(
        "10000",
        title="Row Limit",
        description="Maximum number of rows to return",
        json_schema_extra={"placeholder": "10000"},
    )


class GoogleAnalyticsRealtimeReportConfig(BaseModel):
    """Run a realtime GA4 report showing current activity."""

    operation: Literal["run_ga4_realtime_report"] = Field(
        "run_ga4_realtime_report",
        title="Run Ga4 Realtime Report",
        description="Run a GA4 realtime report",
        json_schema_extra={
            "ui:hidden": True,
            "const": "run_ga4_realtime_report",
            "x-category": "Report",
            "x-is-trigger": False,
            "x-display-name": "Run Ga4 Realtime Report",
        },
    )
    property_id: str = Field(
        ...,
        title="Property ID",
        description="GA4 property ID (numeric, e.g. 123456789)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "property_id",
                "placeholder": "Select a GA4 property...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter property ID",
            },
            "x-resource-type": "google_analytics_property",
        },
    )
    dimensions: str = Field(
        "unifiedScreenName",
        title="Dimensions",
        description="Comma-separated realtime dimension names (e.g. unifiedScreenName, country, city)",
        json_schema_extra={"placeholder": "unifiedScreenName, country"},
    )
    metrics: str = Field(
        "activeUsers",
        title="Metrics",
        description="Comma-separated realtime metric names (e.g. activeUsers, screenPageViews)",
        json_schema_extra={"placeholder": "activeUsers, screenPageViews"},
    )
    limit: str = Field(
        "100",
        title="Row Limit",
        description="Maximum number of rows to return",
        json_schema_extra={"placeholder": "100"},
    )


class GoogleAnalyticsGetMetadataConfig(BaseModel):
    """Get available dimensions and metrics for a GA4 property."""

    operation: Literal["fetch_ga4_dimensions_and_metrics"] = Field(
        "fetch_ga4_dimensions_and_metrics",
        title="Fetch Ga4 Dimensions and Metrics",
        description="List available dimensions and metrics",
        json_schema_extra={
            "ui:hidden": True,
            "const": "fetch_ga4_dimensions_and_metrics",
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Fetch Ga4 Dimensions and Metrics",
        },
    )
    property_id: str = Field(
        ...,
        title="Property ID",
        description="GA4 property ID (numeric, e.g. 123456789)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "property_id",
                "placeholder": "Select a GA4 property...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter property ID",
            },
            "x-resource-type": "google_analytics_property",
        },
    )


GoogleAnalyticsConfig = Annotated[
    Union[
        GoogleAnalyticsRunReportConfig,
        GoogleAnalyticsRealtimeReportConfig,
        GoogleAnalyticsGetMetadataConfig,
    ],
    Discriminator("operation"),
]


class GoogleAnalyticsNodeConfig(
    NodeConfig[GoogleAnalyticsConfig, GoogleAnalyticsOAuthCredential]
):
    pass


# ============================================================================
# Node Implementation
# ============================================================================


class GoogleAnalyticsNode(WorkflowNode):
    edit_examples = [
        "Get traffic by source for last 30 days and identify top channels",
        "Run realtime report to see current active users on website now",
        "Get conversion metrics for mobile vs desktop and compare rates",
        "List available metrics and dimensions for creating custom reports",
        "Get traffic to landing pages and filter for sessions over 2 minutes",
        "Get conversion funnel data for Q2 and compare with Q1 performance",
        "Run report with geographic data and identify highest value regions",
    ]

    scope_registry = GOOGLE_ANALYTICS_SCOPES
    connection_evidence = ConnectionEvidence(
        field="property_id",
        noun="GA4 properties",
    )

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        return GoogleAnalyticsNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name == "property_id":
            return await cls._list_properties(credential_data, page_token, search=search)
        return {"options": [], "next_page_token": None}

    @classmethod
    async def _list_properties(
        cls,
        credential_data: Dict[str, Any],
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List GA4 properties (one option per property across all accounts).

        GA4 ``accountSummaries`` has no name filter, so search mode delegates
        to :func:`load_paginated_options` for the paginate-and-filter pass.
        """
        access_token = require_credential_token(
            credential_data.get("access_token"),
            "Connect a Google account to load GA4 properties",
        )

        async def fetch_page(
            cursor: Optional[str],
        ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
            params: Dict[str, Any] = {"pageSize": 200}
            if cursor:
                params["pageToken"] = cursor
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{GA4_ADMIN_API_BASE}/accountSummaries",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
            options = [
                {
                    "label": (
                        f"{prop.get('displayName', prop.get('property', '').replace('properties/', ''))}"
                        f" ({account.get('displayName', 'Unknown')})"
                    ),
                    "value": prop.get("property", "").replace("properties/", ""),
                }
                for account in (data.get("accountSummaries") or [])
                for prop in (account.get("propertySummaries") or [])
            ]
            return options, data.get("nextPageToken")

        return await load_paginated_options(
            fetch_page,
            page_token=page_token,
            search=search,
            log_label="GoogleAnalyticsNode._list_properties",
        )

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="google",
        )

    async def _ensure_fresh_token(self, credentials) -> str:
        """Return a valid Google Analytics access token, refreshing + persisting if expired."""
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
            return {"error": "No Google Analytics credentials configured"}

        access_token = await self._ensure_fresh_token(credentials)

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        if config.operation == "run_ga4_standard_report":
            return await self._run_report(config, headers)
        elif config.operation == "run_ga4_realtime_report":
            return await self._run_realtime_report(config, headers)
        elif config.operation == "fetch_ga4_dimensions_and_metrics":
            return await self._get_metadata(config, headers)

        return {"error": f"Unknown operation: {config.operation}"}

    async def _run_report(
        self, config: GoogleAnalyticsRunReportConfig, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        dimensions = [
            {"name": d.strip()} for d in config.dimensions.split(",") if d.strip()
        ]
        metrics = [{"name": m.strip()} for m in config.metrics.split(",") if m.strip()]

        date_ranges = [{"startDate": config.start_date, "endDate": config.end_date}]
        if config.compare_start_date and config.compare_end_date:
            date_ranges.append(
                {
                    "startDate": config.compare_start_date,
                    "endDate": config.compare_end_date,
                }
            )

        body: Dict[str, Any] = {
            "dateRanges": date_ranges,
            "dimensions": dimensions,
            "metrics": metrics,
            "limit": int(config.limit) if config.limit else 10000,
        }

        if config.dimension_filter:
            try:
                body["dimensionFilter"] = json.loads(config.dimension_filter)
            except json.JSONDecodeError:
                return {
                    "error": f"Invalid dimension_filter JSON: {config.dimension_filter}"
                }

        if config.metric_filter:
            try:
                body["metricFilter"] = json.loads(config.metric_filter)
            except json.JSONDecodeError:
                return {"error": f"Invalid metric_filter JSON: {config.metric_filter}"}

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GA4_DATA_API_BASE}/properties/{config.property_id}:runReport",
                headers=headers,
                json=body,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()

        return self._format_report(data)

    async def _run_realtime_report(
        self, config: GoogleAnalyticsRealtimeReportConfig, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        dimensions = [
            {"name": d.strip()} for d in config.dimensions.split(",") if d.strip()
        ]
        metrics = [{"name": m.strip()} for m in config.metrics.split(",") if m.strip()]

        body: Dict[str, Any] = {
            "dimensions": dimensions,
            "metrics": metrics,
            "limit": int(config.limit) if config.limit else 100,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GA4_DATA_API_BASE}/properties/{config.property_id}:runRealtimeReport",
                headers=headers,
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

        return self._format_report(data)

    async def _get_metadata(
        self, config: GoogleAnalyticsGetMetadataConfig, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GA4_DATA_API_BASE}/properties/{config.property_id}/metadata",
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

        dimensions = [
            {
                "api_name": d["apiName"],
                "display_name": d.get("uiName", d["apiName"]),
                "category": d.get("category", ""),
            }
            for d in data.get("dimensions", [])
        ]
        metrics = [
            {
                "api_name": m["apiName"],
                "display_name": m.get("uiName", m["apiName"]),
                "category": m.get("category", ""),
            }
            for m in data.get("metrics", [])
        ]

        return {"dimensions": dimensions, "metrics": metrics}

    @staticmethod
    def _format_report(data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert GA4 API response into a flat rows structure."""
        dim_headers = [h.get("name", "") for h in data.get("dimensionHeaders", [])]
        metric_headers = [h.get("name", "") for h in data.get("metricHeaders", [])]
        headers = dim_headers + metric_headers

        rows = []
        for row in data.get("rows", []):
            dim_values = [v.get("value", "") for v in row.get("dimensionValues", [])]
            metric_values = [v.get("value", "") for v in row.get("metricValues", [])]
            rows.append(dict(zip(headers, dim_values + metric_values)))

        return {
            "headers": headers,
            "rows": rows,
            "row_count": data.get("rowCount", len(rows)),
            "metadata": {
                "dimension_headers": dim_headers,
                "metric_headers": metric_headers,
            },
        }
