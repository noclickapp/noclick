"""
Google Ads workflow node implementation.
Pulls campaign, ad group, keyword, and search term data via the Google Ads REST API.

Supports operations: get_campaign_performance, get_ad_group_performance,
get_keyword_performance, get_search_terms, search.
"""

import json
import logging
from typing import Dict, Any, Optional, Union, Type, List, Literal, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import require_credential_token
from nodes.oauth.google_oauth import is_token_expired, refresh_access_token
from nodes.scopes.google_cloud import GOOGLE_ADS_SCOPES

logger = logging.getLogger(__name__)

GOOGLE_ADS_API_VERSION = "v17"
GOOGLE_ADS_API_BASE = f"https://googleads.googleapis.com/{GOOGLE_ADS_API_VERSION}"


# ============================================================================
# Credential Schema
# ============================================================================


class GoogleAdsOAuthCredential(BaseModel):
    """OAuth credential for Google Ads access."""

    credential_type: Literal["google_ads_oauth"] = Field(
        "google_ads_oauth", json_schema_extra={"ui:hidden": True}
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
            "https://www.googleapis.com/auth/adwords",
        ],
    })


# ============================================================================
# Shared base for all Google Ads operations (developer token + login customer ID)
# ============================================================================


class _GoogleAdsBaseConfig(BaseModel):
    """Base fields shared by all Google Ads operations."""

    developer_token: str = Field(
        ...,
        title="Developer Token",
        description="Google Ads API developer token from your manager account's API Center",
        json_schema_extra={
            "x-help-url": "https://ads.google.com/home/tools/manager-accounts/",
            "ui:help": "Found in your Google Ads Manager Account → Tools → API Center",
        },
    )
    customer_id: str = Field(
        ...,
        title="Customer ID",
        description="Google Ads customer/account ID (10 digits, no dashes, e.g. 1234567890)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "customer_id",
                "placeholder": "Select an account...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter customer ID (no dashes)",
            },
            "x-resource-type": "google_ads_customer",
        },
    )
    login_customer_id: Optional[str] = Field(
        None,
        title="Manager Account ID",
        description="If accessing via a manager (MCC) account, enter the manager's customer ID here",
        json_schema_extra={
            "placeholder": "Manager account ID (optional)",
            "ui:help": "Required when your OAuth user accesses client accounts through a manager account",
        },
    )


# ============================================================================
# Configuration Models
# ============================================================================


class GoogleAdsGetCampaignPerformanceConfig(_GoogleAdsBaseConfig):
    """Get performance metrics for campaigns in a Google Ads account."""

    operation: Literal["get_campaign_performance_metrics"] = Field(
        "get_campaign_performance_metrics",
        title="Get Campaign Performance Metrics",
        description="Get campaign performance",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_campaign_performance_metrics",
            "x-category": "General",
            "x-is-trigger": False,
            "x-display-name": "Get Campaign Performance Metrics",
        },
    )
    start_date: str = Field(
        "",
        title="Start Date",
        description="Start date in YYYY-MM-DD format (leave empty for last 30 days)",
        json_schema_extra={"placeholder": "YYYY-MM-DD (optional)"},
    )
    end_date: str = Field(
        "",
        title="End Date",
        description="End date in YYYY-MM-DD format (leave empty for today)",
        json_schema_extra={"placeholder": "YYYY-MM-DD (optional)"},
    )
    campaign_status: str = Field(
        "all",
        title="Campaign Status",
        description="Filter by campaign status",
        json_schema_extra={
            "enum": ["all", "ENABLED", "PAUSED", "REMOVED"],
            "enumNames": ["All", "Enabled", "Paused", "Removed"],
            "x-enum-searchable": True,
        },
    )


class GoogleAdsGetAdGroupPerformanceConfig(_GoogleAdsBaseConfig):
    """Get performance metrics for ad groups in a Google Ads account."""

    operation: Literal["get_ad_group_performance_metrics"] = Field(
        "get_ad_group_performance_metrics",
        title="Get Ad Group Performance Metrics",
        description="Get ad group performance",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_ad_group_performance_metrics",
            "x-category": "General",
            "x-is-trigger": False,
            "x-display-name": "Get Ad Group Performance Metrics",
        },
    )
    start_date: str = Field(
        "",
        title="Start Date",
        description="Start date in YYYY-MM-DD format (leave empty for last 30 days)",
        json_schema_extra={"placeholder": "YYYY-MM-DD (optional)"},
    )
    end_date: str = Field(
        "",
        title="End Date",
        description="End date in YYYY-MM-DD format (leave empty for today)",
        json_schema_extra={"placeholder": "YYYY-MM-DD (optional)"},
    )
    campaign_id: Optional[str] = Field(
        None,
        title="Campaign ID",
        description="Filter by specific campaign ID (optional)",
        json_schema_extra={"placeholder": "Campaign ID (optional)"},
    )


class GoogleAdsGetKeywordPerformanceConfig(_GoogleAdsBaseConfig):
    """Get performance metrics for keywords across campaigns."""

    operation: Literal["get_keyword_performance_metrics"] = Field(
        "get_keyword_performance_metrics",
        title="Get Keyword Performance Metrics",
        description="Get keyword performance",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_keyword_performance_metrics",
            "x-category": "General",
            "x-is-trigger": False,
            "x-display-name": "Get Keyword Performance Metrics",
        },
    )
    start_date: str = Field(
        "",
        title="Start Date",
        description="Start date in YYYY-MM-DD format (leave empty for last 30 days)",
        json_schema_extra={"placeholder": "YYYY-MM-DD (optional)"},
    )
    end_date: str = Field(
        "",
        title="End Date",
        description="End date in YYYY-MM-DD format (leave empty for today)",
        json_schema_extra={"placeholder": "YYYY-MM-DD (optional)"},
    )
    campaign_id: Optional[str] = Field(
        None,
        title="Campaign ID",
        description="Filter by specific campaign ID (optional)",
        json_schema_extra={"placeholder": "Campaign ID (optional)"},
    )


class GoogleAdsGetSearchTermsConfig(_GoogleAdsBaseConfig):
    """Get search terms that triggered your ads — reveals actual user queries."""

    operation: Literal["get_search_terms_triggering_ads"] = Field(
        "get_search_terms_triggering_ads",
        title="Get Search Terms Triggering Ads",
        description="Get search terms report",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_search_terms_triggering_ads",
            "x-category": "General",
            "x-is-trigger": False,
            "x-display-name": "Get Search Terms Triggering Ads",
        },
    )
    start_date: str = Field(
        "",
        title="Start Date",
        description="Start date in YYYY-MM-DD format (leave empty for last 30 days)",
        json_schema_extra={"placeholder": "YYYY-MM-DD (optional)"},
    )
    end_date: str = Field(
        "",
        title="End Date",
        description="End date in YYYY-MM-DD format (leave empty for today)",
        json_schema_extra={"placeholder": "YYYY-MM-DD (optional)"},
    )
    campaign_id: Optional[str] = Field(
        None,
        title="Campaign ID",
        description="Filter by specific campaign ID (optional)",
        json_schema_extra={"placeholder": "Campaign ID (optional)"},
    )


class GoogleAdsSearchConfig(_GoogleAdsBaseConfig):
    """Run a custom GAQL (Google Ads Query Language) query."""

    operation: Literal["run_gaql_query"] = Field(
        "run_gaql_query",
        title="Run Gaql Query",
        description="Run a custom GAQL query",
        json_schema_extra={
            "ui:hidden": True,
            "const": "run_gaql_query",
            "x-category": "General",
            "x-is-trigger": False,
            "x-display-name": "Run Gaql Query",
        },
    )
    query: str = Field(
        ...,
        title="GAQL Query",
        description="Google Ads Query Language query",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "sql",
            "placeholder": "SELECT campaign.name, metrics.impressions FROM campaign WHERE segments.date DURING LAST_30_DAYS",
        },
    )


GoogleAdsConfig = Annotated[
    Union[
        GoogleAdsGetCampaignPerformanceConfig,
        GoogleAdsGetAdGroupPerformanceConfig,
        GoogleAdsGetKeywordPerformanceConfig,
        GoogleAdsGetSearchTermsConfig,
        GoogleAdsSearchConfig,
    ],
    Discriminator("operation"),
]


class GoogleAdsNodeConfig(NodeConfig[GoogleAdsConfig, GoogleAdsOAuthCredential]):
    pass


# ============================================================================
# Node Implementation
# ============================================================================


class GoogleAdsNode(WorkflowNode):
    edit_examples = [
        "Get campaign performance for Q2 and identify highest ROI campaigns",
        "Get ad group stats and find which groups have lowest click-through rates",
        "Get keyword performance and bid recommendations for top performers",
        "Get search terms report and identify negative keywords to exclude",
        "Run GAQL query to get impressions by device type last 30 days",
        "Get campaign performance by status and pause underperforming campaigns",
        "Get conversion data by campaign and calculate cost per acquisition",
    ]

    scope_registry = GOOGLE_ADS_SCOPES
    connection_evidence = ConnectionEvidence(
        field="customer_id",
        noun="ad accounts",
    )

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        return GoogleAdsNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name == "customer_id":
            developer_token = (context or {}).get("developer_token", "")
            login_customer_id = (context or {}).get("login_customer_id")
            return await cls._list_accessible_customers(
                credential_data, developer_token, login_customer_id, search=search
            )
        return {"options": [], "next_page_token": None}

    @classmethod
    async def _list_accessible_customers(
        cls,
        credential_data: Dict[str, Any],
        developer_token: str,
        login_customer_id: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        access_token = require_credential_token(
            credential_data.get("access_token"),
            "Connect a Google Ads account to load accounts",
        )

        if not developer_token:
            raise ValueError("Set a Google Ads developer token to load accounts")

        headers = cls._build_headers(access_token, developer_token, login_customer_id)

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GOOGLE_ADS_API_BASE}/customers:listAccessibleCustomers",
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

        options = []
        for resource_name in data.get("resourceNames", []):
            cid = resource_name.replace("customers/", "")
            try:
                query_resp = await cls._search_query(
                    access_token,
                    developer_token,
                    cid,
                    "SELECT customer.descriptive_name, customer.id FROM customer LIMIT 1",
                    login_customer_id,
                )
                name = cid
                for result in query_resp.get("results", []):
                    name = result.get("customer", {}).get("descriptiveName", cid)
                options.append({"label": f"{name} ({cid})", "value": cid})
            except Exception:
                options.append({"label": cid, "value": cid})

        return {"options": options, "next_page_token": None}

    @staticmethod
    def _build_headers(
        access_token: str, developer_token: str, login_customer_id: Optional[str] = None
    ) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "developer-token": developer_token,
            "Content-Type": "application/json",
        }
        if login_customer_id:
            headers["login-customer-id"] = login_customer_id.replace("-", "")
        return headers

    @classmethod
    async def _search_query(
        cls,
        access_token: str,
        developer_token: str,
        customer_id: str,
        query: str,
        login_customer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        headers = cls._build_headers(access_token, developer_token, login_customer_id)

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GOOGLE_ADS_API_BASE}/customers/{customer_id}/googleAds:search",
                headers=headers,
                json={"query": query},
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()

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
        """Return a valid Google Ads access token, refreshing + persisting if expired."""
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
            return {"error": "No Google Ads credentials configured"}

        access_token = await self._ensure_fresh_token(credentials)

        developer_token = config.developer_token
        login_customer_id = getattr(config, "login_customer_id", None)

        if config.operation == "get_campaign_performance_metrics":
            return await self._get_campaign_performance(
                config, access_token, developer_token, login_customer_id
            )
        elif config.operation == "get_ad_group_performance_metrics":
            return await self._get_ad_group_performance(
                config, access_token, developer_token, login_customer_id
            )
        elif config.operation == "get_keyword_performance_metrics":
            return await self._get_keyword_performance(
                config, access_token, developer_token, login_customer_id
            )
        elif config.operation == "get_search_terms_triggering_ads":
            return await self._get_search_terms(
                config, access_token, developer_token, login_customer_id
            )
        elif config.operation == "run_gaql_query":
            return await self._search(
                config, access_token, developer_token, login_customer_id
            )

        return {"error": f"Unknown operation: {config.operation}"}

    async def _get_campaign_performance(
        self,
        config: GoogleAdsGetCampaignPerformanceConfig,
        access_token: str,
        developer_token: str,
        login_customer_id: Optional[str],
    ) -> Dict[str, Any]:
        date_clause = self._build_date_clause(config.start_date, config.end_date)
        status_clause = ""
        if config.campaign_status != "all":
            status_clause = f" AND campaign.status = '{config.campaign_status}'"

        query = (
            "SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type, "
            "metrics.impressions, metrics.clicks, metrics.cost_micros, "
            "metrics.conversions, metrics.conversions_value, "
            "metrics.ctr, metrics.average_cpc, metrics.average_cpm, "
            "segments.date "
            f"FROM campaign WHERE {date_clause}{status_clause} "
            "ORDER BY metrics.cost_micros DESC"
        )

        data = await self._search_query(
            access_token, developer_token, config.customer_id, query, login_customer_id
        )
        return self._format_results(data)

    async def _get_ad_group_performance(
        self,
        config: GoogleAdsGetAdGroupPerformanceConfig,
        access_token: str,
        developer_token: str,
        login_customer_id: Optional[str],
    ) -> Dict[str, Any]:
        date_clause = self._build_date_clause(config.start_date, config.end_date)
        campaign_clause = ""
        if config.campaign_id:
            campaign_clause = f" AND campaign.id = {config.campaign_id}"

        query = (
            "SELECT ad_group.id, ad_group.name, ad_group.status, "
            "campaign.name, "
            "metrics.impressions, metrics.clicks, metrics.cost_micros, "
            "metrics.conversions, metrics.ctr, metrics.average_cpc, "
            "segments.date "
            f"FROM ad_group WHERE {date_clause}{campaign_clause} "
            "ORDER BY metrics.cost_micros DESC"
        )

        data = await self._search_query(
            access_token, developer_token, config.customer_id, query, login_customer_id
        )
        return self._format_results(data)

    async def _get_keyword_performance(
        self,
        config: GoogleAdsGetKeywordPerformanceConfig,
        access_token: str,
        developer_token: str,
        login_customer_id: Optional[str],
    ) -> Dict[str, Any]:
        date_clause = self._build_date_clause(config.start_date, config.end_date)
        campaign_clause = ""
        if config.campaign_id:
            campaign_clause = f" AND campaign.id = {config.campaign_id}"

        query = (
            "SELECT campaign.name, ad_group.name, "
            "ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type, "
            "ad_group_criterion.quality_info.quality_score, "
            "metrics.impressions, metrics.clicks, metrics.cost_micros, "
            "metrics.conversions, metrics.ctr, metrics.average_cpc "
            f"FROM keyword_view WHERE {date_clause}{campaign_clause} "
            "ORDER BY metrics.impressions DESC"
        )

        data = await self._search_query(
            access_token, developer_token, config.customer_id, query, login_customer_id
        )
        return self._format_results(data)

    async def _get_search_terms(
        self,
        config: GoogleAdsGetSearchTermsConfig,
        access_token: str,
        developer_token: str,
        login_customer_id: Optional[str],
    ) -> Dict[str, Any]:
        date_clause = self._build_date_clause(config.start_date, config.end_date)
        campaign_clause = ""
        if config.campaign_id:
            campaign_clause = f" AND campaign.id = {config.campaign_id}"

        query = (
            "SELECT campaign.name, ad_group.name, "
            "search_term_view.search_term, search_term_view.status, "
            "metrics.impressions, metrics.clicks, metrics.cost_micros, "
            "metrics.conversions, metrics.ctr, metrics.average_cpc "
            f"FROM search_term_view WHERE {date_clause}{campaign_clause} "
            "ORDER BY metrics.impressions DESC"
        )

        data = await self._search_query(
            access_token, developer_token, config.customer_id, query, login_customer_id
        )
        return self._format_results(data)

    async def _search(
        self,
        config: GoogleAdsSearchConfig,
        access_token: str,
        developer_token: str,
        login_customer_id: Optional[str],
    ) -> Dict[str, Any]:
        data = await self._search_query(
            access_token,
            developer_token,
            config.customer_id,
            config.query,
            login_customer_id,
        )
        return self._format_results(data)

    @staticmethod
    def _build_date_clause(start_date: str, end_date: str) -> str:
        if start_date and end_date:
            return f"segments.date BETWEEN '{start_date}' AND '{end_date}'"
        return "segments.date DURING LAST_30_DAYS"

    @staticmethod
    def _format_results(data: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten nested GAQL results into a rows structure."""
        results = data.get("results", [])
        if not results:
            return {"rows": [], "row_count": 0}

        rows = []
        for result in results:
            row: Dict[str, Any] = {}
            for category, fields in result.items():
                if isinstance(fields, dict):
                    for key, value in fields.items():
                        if key == "costMicros" and value:
                            row[f"{category}_{key}"] = value
                            row[f"{category}_cost"] = round(int(value) / 1_000_000, 2)
                        else:
                            row[f"{category}_{key}"] = value
                else:
                    row[category] = fields
            rows.append(row)

        return {"rows": rows, "row_count": len(rows)}
