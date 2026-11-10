"""
Ahrefs SEO automation node.

Provides workflow integration with the Ahrefs API v3 for operations including:
- Site Explorer: overview, domain rating, backlinks, broken backlinks, referring
  domains, anchors, organic keywords, organic competitors, top pages, paid pages,
  best by external links, linked domains, metrics history
- Keywords Explorer: overview, volume history, volume by country, matching terms,
  related terms, search suggestions
- SERP Overview, Batch Analysis
- Site Audit: page explorer, projects list
- Rank Tracker: overview
- Management: list projects, add keywords, add competitors
- Subscription: limits and usage
- Public: crawler IP ranges

Authentication: API Key (Bearer token). OAuth 2.0 (Ahrefs Connect) is also
supported by the provider but uses a brand-new provider with PKCE and no refresh
tokens; the API key is the simplest fully-working self-serve path.

API Base URL: https://api.ahrefs.com/v3
Documentation: https://docs.ahrefs.com/en/api/docs/introduction

Webhooks/triggers: none. Ahrefs API v3 is request/response only, so this node
ships no trigger.
"""

from datetime import date as Date
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence

logger = logging.getLogger(__name__)

AHREFS_API_BASE = "https://api.ahrefs.com/v3"

# Default field selections per endpoint family. Ahrefs requires an explicit
# `select` on most data endpoints; these give a sensible default payload.
DEFAULT_BACKLINKS_SELECT = "url_from,url_to,anchor,domain_rating_source,traffic,link_type,first_seen"
DEFAULT_REFDOMAINS_SELECT = "domain,domain_rating,traffic_domain,dofollow_refdomains,links_to_target"
DEFAULT_ANCHORS_SELECT = "anchor,refdomains,links_to_target"
DEFAULT_ORGANIC_KEYWORDS_SELECT = "keyword,volume,keyword_difficulty,cpc,best_position,sum_traffic,best_position_url"
DEFAULT_ORGANIC_COMPETITORS_SELECT = "competitor_domain,keywords_common,keywords_competitor,traffic"
DEFAULT_TOP_PAGES_SELECT = "url,sum_traffic,value,keywords,top_keyword,top_keyword_volume"
DEFAULT_PAID_PAGES_SELECT = "url,sum_traffic,value,keywords,ads_count"
DEFAULT_BEST_BY_LINKS_SELECT = "url_to,links_to_target,url_rating_target,refdomains_target"
DEFAULT_LINKED_DOMAINS_SELECT = "domain,domain_rating,links_from_target,dofollow_links"
DEFAULT_METRICS_HISTORY_SELECT = "date,org_traffic,org_cost"
DEFAULT_KE_OVERVIEW_SELECT = "keyword,volume,difficulty,cpc,clicks,traffic_potential"
DEFAULT_SERP_SELECT = "position,url,title,domain_rating,traffic,backlinks,refdomains"
DEFAULT_BATCH_SELECT = "url,domain_rating,org_traffic,refdomains,backlinks"


# ============================================================================
# Credential Schema
# ============================================================================


class AhrefsAPIKeyCredential(BaseModel):
    """API Key credential for Ahrefs."""

    credential_type: Literal["ahrefs_api_key"] = Field(
        "ahrefs_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Ahrefs API key from Account settings -> API keys (workspace owners/admins only)",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://docs.ahrefs.com/en/api/docs/api-keys-creation-and-management",
            "x-credential-instructions": "Generate an API v3 key in Ahrefs Account settings → API keys. Only workspace owners and admins can create keys.",
        }
    )


AhrefsCredential = AhrefsAPIKeyCredential


# ============================================================================
# Shared field helpers
# ============================================================================


def _target_field(description: str = "Domain or URL to analyze (e.g. ahrefs.com)") -> Any:
    return Field(..., title="Target", description=description)


def _mode_field() -> Any:
    return Field(
        "subdomains",
        title="Mode",
        description="How to interpret the target",
        json_schema_extra={
            "enum": ["exact", "prefix", "domain", "subdomains"],
            "enumNames": ["Exact URL", "Prefix (path)", "Domain", "Domain + subdomains"],
            "x-enum-searchable": True,
        },
    )


def _limit_field(default: str = "100") -> Any:
    return Field(
        default, title="Limit", description="Maximum number of rows to return"
    )


def _country_field(default: Optional[str] = None) -> Any:
    return Field(
        default,
        title="Country",
        description="2-letter country code (e.g. us, gb). Defaults to global/US.",
    )


# ============================================================================
# Site Explorer operation configs
# ============================================================================


class AhrefsSiteOverviewConfig(BaseModel):
    """Domain/URL overview: DR, backlinks, referring domains, traffic and value."""

    operation: Literal["site_overview"] = Field(
        "site_overview",
        json_schema_extra={
            "const": "site_overview",
            "ui:hidden": True,
            "x-category": "Site Explorer",
            "x-is-trigger": False,
            "x-display-name": "Site Explorer Overview",
        },
        title="Site Explorer Overview",
    )
    target: str = _target_field()
    mode: str = _mode_field()
    protocol: Optional[str] = Field(
        "both",
        title="Protocol",
        description="Which protocol to consider",
        json_schema_extra={
            "enum": ["both", "http", "https"],
            "x-enum-searchable": True,
        },
    )

    date: Date = Field(..., title="Date", description="Snapshot date (YYYY-MM-DD)")


class AhrefsDomainRatingConfig(BaseModel):
    """Domain Rating (DR) for a target."""

    operation: Literal["domain_rating"] = Field(
        "domain_rating",
        json_schema_extra={
            "const": "domain_rating",
            "ui:hidden": True,
            "x-category": "Site Explorer",
            "x-is-trigger": False,
            "x-display-name": "Domain Rating",
        },
        title="Domain Rating",
    )
    target: str = _target_field()
    date: Date = Field(
        ..., title="Date", description="Snapshot date (YYYY-MM-DD)"
    )


class AhrefsBacklinksConfig(BaseModel):
    """List of backlinks pointing to a target (anchor, DR, traffic, link type)."""

    operation: Literal["backlinks"] = Field(
        "backlinks",
        json_schema_extra={
            "const": "backlinks",
            "ui:hidden": True,
            "x-category": "Site Explorer",
            "x-is-trigger": False,
            "x-display-name": "Backlinks",
        },
        title="Backlinks",
    )
    target: str = _target_field()
    mode: str = _mode_field()
    limit: Optional[str] = _limit_field()
    select: Optional[str] = Field(
        DEFAULT_BACKLINKS_SELECT,
        title="Fields",
        description="Comma-separated list of fields to return",
    )
    order_by: Optional[str] = Field(
        None, title="Order By", description="Sort expression, e.g. 'traffic:desc'"
    )


class AhrefsBrokenBacklinksConfig(BaseModel):
    """Backlinks pointing to dead/404 pages on the target."""

    operation: Literal["broken_backlinks"] = Field(
        "broken_backlinks",
        json_schema_extra={
            "const": "broken_backlinks",
            "ui:hidden": True,
            "x-category": "Site Explorer",
            "x-is-trigger": False,
            "x-display-name": "Broken Backlinks",
        },
        title="Broken Backlinks",
    )
    target: str = _target_field()
    mode: str = _mode_field()
    limit: Optional[str] = _limit_field()
    select: Optional[str] = Field(
        DEFAULT_BACKLINKS_SELECT, title="Fields", description="Comma-separated fields to return"
    )


class AhrefsRefDomainsConfig(BaseModel):
    """Domains linking to the target."""

    operation: Literal["refdomains"] = Field(
        "refdomains",
        json_schema_extra={
            "const": "refdomains",
            "ui:hidden": True,
            "x-category": "Site Explorer",
            "x-is-trigger": False,
            "x-display-name": "Referring Domains",
        },
        title="Referring Domains",
    )
    target: str = _target_field()
    mode: str = _mode_field()
    limit: Optional[str] = _limit_field()
    select: Optional[str] = Field(
        DEFAULT_REFDOMAINS_SELECT, title="Fields", description="Comma-separated fields to return"
    )
    order_by: Optional[str] = Field(
        None, title="Order By", description="Sort expression, e.g. 'domain_rating:desc'"
    )


class AhrefsAnchorsConfig(BaseModel):
    """Anchor-text distribution of backlinks to the target."""

    operation: Literal["anchors"] = Field(
        "anchors",
        json_schema_extra={
            "const": "anchors",
            "ui:hidden": True,
            "x-category": "Site Explorer",
            "x-is-trigger": False,
            "x-display-name": "Anchors",
        },
        title="Anchors",
    )
    target: str = _target_field()
    mode: str = _mode_field()
    limit: Optional[str] = _limit_field()
    select: Optional[str] = Field(
        DEFAULT_ANCHORS_SELECT, title="Fields", description="Comma-separated fields to return"
    )


class AhrefsOrganicKeywordsConfig(BaseModel):
    """Keywords the target ranks for in organic search."""

    operation: Literal["organic_keywords"] = Field(
        "organic_keywords",
        json_schema_extra={
            "const": "organic_keywords",
            "ui:hidden": True,
            "x-category": "Site Explorer",
            "x-is-trigger": False,
            "x-display-name": "Organic Keywords",
        },
        title="Organic Keywords",
    )
    target: str = _target_field()
    mode: str = _mode_field()
    country: Optional[str] = _country_field("us")
    limit: Optional[str] = _limit_field()
    select: Optional[str] = Field(
        DEFAULT_ORGANIC_KEYWORDS_SELECT, title="Fields", description="Comma-separated fields to return"
    )
    order_by: Optional[str] = Field(
        None, title="Order By", description="Sort expression, e.g. 'traffic:desc'"
    )

    date: Date = Field(..., title="Date", description="Snapshot date (YYYY-MM-DD)")


class AhrefsOrganicCompetitorsConfig(BaseModel):
    """Domains competing for the target's organic keywords."""

    operation: Literal["organic_competitors"] = Field(
        "organic_competitors",
        json_schema_extra={
            "const": "organic_competitors",
            "ui:hidden": True,
            "x-category": "Site Explorer",
            "x-is-trigger": False,
            "x-display-name": "Organic Competitors",
        },
        title="Organic Competitors",
    )
    target: str = _target_field()
    mode: str = _mode_field()
    country: Optional[str] = _country_field("us")
    limit: Optional[str] = _limit_field()
    select: Optional[str] = Field(
        DEFAULT_ORGANIC_COMPETITORS_SELECT, title="Fields", description="Comma-separated fields to return"
    )

    date: Date = Field(..., title="Date", description="Snapshot date (YYYY-MM-DD)")


class AhrefsTopPagesConfig(BaseModel):
    """Best-performing pages of the target by organic traffic."""

    operation: Literal["top_pages"] = Field(
        "top_pages",
        json_schema_extra={
            "const": "top_pages",
            "ui:hidden": True,
            "x-category": "Site Explorer",
            "x-is-trigger": False,
            "x-display-name": "Top Pages",
        },
        title="Top Pages",
    )
    target: str = _target_field()
    mode: str = _mode_field()
    country: Optional[str] = _country_field("us")
    limit: Optional[str] = _limit_field()
    select: Optional[str] = Field(
        DEFAULT_TOP_PAGES_SELECT, title="Fields", description="Comma-separated fields to return"
    )

    date: Date = Field(..., title="Date", description="Snapshot date (YYYY-MM-DD)")


class AhrefsPaidPagesConfig(BaseModel):
    """Pages of the target running paid (PPC) ads."""

    operation: Literal["paid_pages"] = Field(
        "paid_pages",
        json_schema_extra={
            "const": "paid_pages",
            "ui:hidden": True,
            "x-category": "Site Explorer",
            "x-is-trigger": False,
            "x-display-name": "Paid Pages",
        },
        title="Paid Pages",
    )
    target: str = _target_field()
    mode: str = _mode_field()
    country: Optional[str] = _country_field("us")
    limit: Optional[str] = _limit_field()
    select: Optional[str] = Field(
        DEFAULT_PAID_PAGES_SELECT, title="Fields", description="Comma-separated fields to return"
    )

    date: Date = Field(..., title="Date", description="Snapshot date (YYYY-MM-DD)")


class AhrefsBestByExternalLinksConfig(BaseModel):
    """Target's pages ranked by number of external backlinks."""

    operation: Literal["best_by_external_links"] = Field(
        "best_by_external_links",
        json_schema_extra={
            "const": "best_by_external_links",
            "ui:hidden": True,
            "x-category": "Site Explorer",
            "x-is-trigger": False,
            "x-display-name": "Best by External Links",
        },
        title="Best by External Links",
    )
    target: str = _target_field()
    mode: str = _mode_field()
    limit: Optional[str] = _limit_field()
    select: Optional[str] = Field(
        DEFAULT_BEST_BY_LINKS_SELECT, title="Fields", description="Comma-separated fields to return"
    )


class AhrefsLinkedDomainsConfig(BaseModel):
    """Outbound domains the target links to."""

    operation: Literal["linked_domains"] = Field(
        "linked_domains",
        json_schema_extra={
            "const": "linked_domains",
            "ui:hidden": True,
            "x-category": "Site Explorer",
            "x-is-trigger": False,
            "x-display-name": "Linked Domains",
        },
        title="Linked Domains",
    )
    target: str = _target_field()
    mode: str = _mode_field()
    limit: Optional[str] = _limit_field()
    select: Optional[str] = Field(
        DEFAULT_LINKED_DOMAINS_SELECT, title="Fields", description="Comma-separated fields to return"
    )


class AhrefsMetricsHistoryConfig(BaseModel):
    """Historical organic traffic / keyword / value metrics over time."""

    operation: Literal["metrics_history"] = Field(
        "metrics_history",
        json_schema_extra={
            "const": "metrics_history",
            "ui:hidden": True,
            "x-category": "Site Explorer",
            "x-is-trigger": False,
            "x-display-name": "Metrics History",
        },
        title="Metrics History",
    )
    target: str = _target_field()
    mode: str = _mode_field()
    country: Optional[str] = _country_field("us")
    date_from: Optional[str] = Field(
        None, title="Date From", description="Start date (YYYY-MM-DD)"
    )
    date_to: Optional[str] = Field(None, title="Date To", description="End date (YYYY-MM-DD)")
    select: Optional[str] = Field(
        DEFAULT_METRICS_HISTORY_SELECT, title="Fields", description="Comma-separated fields to return"
    )


# ============================================================================
# Keywords Explorer operation configs
# ============================================================================


class AhrefsKeywordsOverviewConfig(BaseModel):
    """Metrics for one or many keywords: volume, KD, CPC, clicks, traffic potential."""

    operation: Literal["keywords_overview"] = Field(
        "keywords_overview",
        json_schema_extra={
            "const": "keywords_overview",
            "ui:hidden": True,
            "x-category": "Keywords Explorer",
            "x-is-trigger": False,
            "x-display-name": "Keywords Explorer Overview",
        },
        title="Keywords Explorer Overview",
    )
    keywords: str = Field(
        ...,
        title="Keywords",
        description="One or more keywords, comma-separated",
    )
    country: Optional[str] = _country_field("us")
    select: Optional[str] = Field(
        DEFAULT_KE_OVERVIEW_SELECT, title="Fields", description="Comma-separated fields to return"
    )


class AhrefsVolumeHistoryConfig(BaseModel):
    """Monthly search-volume history for a keyword."""

    operation: Literal["volume_history"] = Field(
        "volume_history",
        json_schema_extra={
            "const": "volume_history",
            "ui:hidden": True,
            "x-category": "Keywords Explorer",
            "x-is-trigger": False,
            "x-display-name": "Volume History",
        },
        title="Volume History",
    )
    keyword: str = Field(..., title="Keyword", description="The keyword to look up")
    country: Optional[str] = _country_field("us")


class AhrefsVolumeByCountryConfig(BaseModel):
    """Search volume of a keyword broken down by country."""

    operation: Literal["volume_by_country"] = Field(
        "volume_by_country",
        json_schema_extra={
            "const": "volume_by_country",
            "ui:hidden": True,
            "x-category": "Keywords Explorer",
            "x-is-trigger": False,
            "x-display-name": "Volume by Country",
        },
        title="Volume by Country",
    )
    keyword: str = Field(..., title="Keyword", description="The keyword to look up")

    countries: Optional[str] = Field(
        None, title="Countries", description="Comma-separated two-letter country codes. Leave blank for all countries."
    )


class AhrefsMatchingTermsConfig(BaseModel):
    """Keyword ideas containing/related to a seed keyword."""

    operation: Literal["matching_terms"] = Field(
        "matching_terms",
        json_schema_extra={
            "const": "matching_terms",
            "ui:hidden": True,
            "x-category": "Keywords Explorer",
            "x-is-trigger": False,
            "x-display-name": "Matching Terms",
        },
        title="Matching Terms",
    )
    keywords: str = Field(
        ..., title="Seed Keywords", description="Seed keyword(s), comma-separated"
    )
    country: Optional[str] = _country_field("us")
    limit: Optional[str] = _limit_field()

    select: str = Field("keyword,volume,difficulty", title="Fields", description="Comma-separated fields to return")


class AhrefsRelatedTermsConfig(BaseModel):
    """Related keyword ideas ('also rank for')."""

    operation: Literal["related_terms"] = Field(
        "related_terms",
        json_schema_extra={
            "const": "related_terms",
            "ui:hidden": True,
            "x-category": "Keywords Explorer",
            "x-is-trigger": False,
            "x-display-name": "Related Terms",
        },
        title="Related Terms",
    )
    keywords: str = Field(
        ..., title="Seed Keywords", description="Seed keyword(s), comma-separated"
    )
    country: Optional[str] = _country_field("us")
    limit: Optional[str] = _limit_field()

    select: str = Field("keyword,volume,difficulty", title="Fields", description="Comma-separated fields to return")


class AhrefsSearchSuggestionsConfig(BaseModel):
    """Autocomplete-style keyword suggestions for a seed."""

    operation: Literal["search_suggestions"] = Field(
        "search_suggestions",
        json_schema_extra={
            "const": "search_suggestions",
            "ui:hidden": True,
            "x-category": "Keywords Explorer",
            "x-is-trigger": False,
            "x-display-name": "Search Suggestions",
        },
        title="Search Suggestions",
    )
    keywords: str = Field(
        ..., title="Seed Keywords", description="Seed keyword(s), comma-separated"
    )
    country: Optional[str] = _country_field("us")
    limit: Optional[str] = _limit_field()
    select: str = Field("keyword,volume,difficulty", title="Fields", description="Comma-separated fields to return")


# ============================================================================
# SERP / Batch operation configs
# ============================================================================

class AhrefsSerpOverviewConfig(BaseModel):
    """Top ~100 organic results for a keyword with per-position SEO metrics."""

    operation: Literal["serp_overview"] = Field(
        "serp_overview",
        json_schema_extra={
            "const": "serp_overview",
            "ui:hidden": True,
            "x-category": "SERP",
            "x-is-trigger": False,
            "x-display-name": "SERP Overview",
        },
        title="SERP Overview",
    )
    keyword: str = Field(..., title="Keyword", description="The keyword to analyze")
    country: Optional[str] = _country_field("us")
    select: Optional[str] = Field(
        DEFAULT_SERP_SELECT, title="Fields", description="Comma-separated fields to return"
    )

    comparison_countries: Optional[str] = Field(
        None, title="Comparison Countries", description="Additional two-letter country codes, comma-separated."
    )
    type: Optional[str] = Field(
        None, title="SERP Types", description="Comma-separated SERP feature types, such as organic. Leave blank for all types."
    )


class AhrefsBatchAnalysisConfig(BaseModel):
    """Core metrics (DR, traffic, refdomains, etc.) for up to 100 targets in one call."""

    operation: Literal["batch_analysis"] = Field(
        "batch_analysis",
        json_schema_extra={
            "const": "batch_analysis",
            "ui:hidden": True,
            "x-category": "Batch",
            "x-is-trigger": False,
            "x-display-name": "Batch Analysis",
        },
        title="Batch Analysis",
    )
    targets: str = Field(
        ...,
        title="Targets",
        description="Up to 100 domains/URLs, comma-separated",
    )
    mode: str = _mode_field()
    select: Optional[str] = Field(
        DEFAULT_BATCH_SELECT, title="Fields", description="Comma-separated fields to return"
    )


# ============================================================================
# Site Audit operation configs
# ============================================================================


class AhrefsSiteAuditProjectsConfig(BaseModel):
    """List the user's Site Audit projects."""

    operation: Literal["site_audit_projects"] = Field(
        "site_audit_projects",
        json_schema_extra={
            "const": "site_audit_projects",
            "ui:hidden": True,
            "x-category": "Site Audit",
            "x-is-trigger": False,
            "x-display-name": "Site Audit Projects",
        },
        title="Site Audit Projects",
    )


class AhrefsSiteAuditPageExplorerConfig(BaseModel):
    """Crawled-page data + issues for a Site Audit project."""

    operation: Literal["site_audit_page_explorer"] = Field(
        "site_audit_page_explorer",
        json_schema_extra={
            "const": "site_audit_page_explorer",
            "ui:hidden": True,
            "x-category": "Site Audit",
            "x-is-trigger": False,
            "x-display-name": "Site Audit Page Explorer",
        },
        title="Site Audit Page Explorer",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="The Site Audit project to query",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "site_audit_project_id",
                "placeholder": "Select a Site Audit project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project ID",
            }
        },
    )
    limit: Optional[str] = _limit_field()


# ============================================================================
# Rank Tracker / Management operation configs
# ============================================================================


class AhrefsRankTrackerOverviewConfig(BaseModel):
    """Ranking overview (tracked keyword positions/visibility) for a project."""

    operation: Literal["rank_tracker_overview"] = Field(
        "rank_tracker_overview",
        json_schema_extra={
            "const": "rank_tracker_overview",
            "ui:hidden": True,
            "x-category": "Rank Tracker",
            "x-is-trigger": False,
            "x-display-name": "Rank Tracker Overview",
        },
        title="Rank Tracker Overview",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="The Rank Tracker project to query",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a Rank Tracker project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project ID",
            }
        },
    )

    date: Date = Field(..., title="Date", description="Snapshot date (YYYY-MM-DD)")

    select: str = Field("keyword,position,traffic", title="Fields", description="Comma-separated fields to return")
    device: Literal["desktop", "mobile"] = Field("desktop", title="Device")


class AhrefsListProjectsConfig(BaseModel):
    """List Rank Tracker projects in the workspace."""

    operation: Literal["list_projects"] = Field(
        "list_projects",
        json_schema_extra={
            "const": "list_projects",
            "ui:hidden": True,
            "x-category": "Management",
            "x-is-trigger": False,
            "x-display-name": "List Projects",
        },
        title="List Projects",
    )


class AhrefsAddKeywordsConfig(BaseModel):
    """Add tracked keywords to a Rank Tracker project."""

    operation: Literal["add_keywords"] = Field(
        "add_keywords",
        json_schema_extra={
            "const": "add_keywords",
            "ui:hidden": True,
            "x-category": "Management",
            "x-is-trigger": False,
            "x-display-name": "Add Keywords",
        },
        title="Add Keywords",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="The Rank Tracker project to add keywords to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a Rank Tracker project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project ID",
            }
        },
    )
    keywords: str = Field(
        ..., title="Keywords", description="Keywords to add, comma-separated"
    )
    country: Optional[str] = _country_field("us")


class AhrefsAddCompetitorsConfig(BaseModel):
    """Add competitors to a Rank Tracker project."""

    operation: Literal["add_competitors"] = Field(
        "add_competitors",
        json_schema_extra={
            "const": "add_competitors",
            "ui:hidden": True,
            "x-category": "Management",
            "x-is-trigger": False,
            "x-display-name": "Add Competitors",
        },
        title="Add Competitors",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="The Rank Tracker project to add competitors to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a Rank Tracker project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project ID",
            }
        },
    )
    competitors: str = Field(
        ..., title="Competitors", description="Competitor domains to add, comma-separated"
    )

    mode: str = _mode_field()


# ============================================================================
# Subscription / Public operation configs
# ============================================================================


class AhrefsLimitsAndUsageConfig(BaseModel):
    """Current API unit limits, consumed units, and remaining quota."""

    operation: Literal["limits_and_usage"] = Field(
        "limits_and_usage",
        json_schema_extra={
            "const": "limits_and_usage",
            "ui:hidden": True,
            "x-category": "Subscription",
            "x-is-trigger": False,
            "x-display-name": "Limits & Usage",
        },
        title="Limits & Usage",
    )


class AhrefsGetLimitsAndUsageConfig(AhrefsLimitsAndUsageConfig):
    """Read-only probe alias; retain limits_and_usage for saved workflows."""

    operation: Literal["get_limits_and_usage"] = Field(
        "get_limits_and_usage",
        json_schema_extra={
            "const": "get_limits_and_usage",
            "ui:hidden": True,
            "x-category": "Subscription",
            "x-is-trigger": False,
            "x-display-name": "Get Limits & Usage",
        },
        title="Get Limits & Usage",
    )


class AhrefsCrawlerIpRangesConfig(BaseModel):
    """Ahrefs (AhrefsBot) crawler IP addresses / ranges (no units)."""

    operation: Literal["crawler_ip_ranges"] = Field(
        "crawler_ip_ranges",
        json_schema_extra={
            "const": "crawler_ip_ranges",
            "ui:hidden": True,
            "x-category": "Public",
            "x-is-trigger": False,
            "x-display-name": "Crawler IP Ranges",
        },
        title="Crawler IP Ranges",
    )


# ============================================================================
# Discriminated Union
# ============================================================================


AhrefsConfig = Annotated[
    Union[
        AhrefsSiteOverviewConfig,
        AhrefsDomainRatingConfig,
        AhrefsBacklinksConfig,
        AhrefsBrokenBacklinksConfig,
        AhrefsRefDomainsConfig,
        AhrefsAnchorsConfig,
        AhrefsOrganicKeywordsConfig,
        AhrefsOrganicCompetitorsConfig,
        AhrefsTopPagesConfig,
        AhrefsPaidPagesConfig,
        AhrefsBestByExternalLinksConfig,
        AhrefsLinkedDomainsConfig,
        AhrefsMetricsHistoryConfig,
        AhrefsKeywordsOverviewConfig,
        AhrefsVolumeHistoryConfig,
        AhrefsVolumeByCountryConfig,
        AhrefsMatchingTermsConfig,
        AhrefsRelatedTermsConfig,
        AhrefsSearchSuggestionsConfig,
        AhrefsSerpOverviewConfig,
        AhrefsBatchAnalysisConfig,
        AhrefsSiteAuditProjectsConfig,
        AhrefsSiteAuditPageExplorerConfig,
        AhrefsRankTrackerOverviewConfig,
        AhrefsListProjectsConfig,
        AhrefsAddKeywordsConfig,
        AhrefsAddCompetitorsConfig,
        AhrefsLimitsAndUsageConfig,
        AhrefsGetLimitsAndUsageConfig,
        AhrefsCrawlerIpRangesConfig,
    ],
    Discriminator("operation"),
]


class AhrefsNodeConfig(NodeConfig[AhrefsConfig, AhrefsCredential]):
    """Full configuration for the Ahrefs node including credentials."""

    pass


# ============================================================================
# HTTP request helper
# ============================================================================


def _comma_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


async def _ahrefs_request(
    api_key: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Ahrefs API v3 request and return a structured result."""
    url = f"{AHREFS_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}
    if json_body:
        json_body = {k: v for k, v in json_body.items() if v is not None}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if not 200 <= response.status_code < 300:
                # Vendor bodies may echo a request header or key. Only the HTTP
                # status crosses the workflow/log boundary.
                if response.status_code == 401:
                    message = "Ahrefs rejected the API key (HTTP 401)"
                elif response.status_code == 403:
                    message = "Ahrefs denied access to this endpoint (HTTP 403)"
                elif response.status_code == 429:
                    message = "Ahrefs rate limit reached (HTTP 429)"
                else:
                    message = f"Ahrefs API request failed (HTTP {response.status_code})"
                logger.warning("[AhrefsNode] %s: HTTP %s", action_name, response.status_code)
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                data: Any = {"success": True}
            else:
                try:
                    data = response.json()
                except Exception:
                    data = None
                if not isinstance(data, (dict, list)) or not data:
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": "Ahrefs returned an invalid JSON response",
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": api_ms},
                    }
            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception:
            # httpx exception strings can contain request URLs and headers.
            logger.warning("[AhrefsNode] Request failed (%s)", action_name)
            return {
                "status": "error",
                "action": action_name,
                "error": "Could not reach the Ahrefs API",
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ============================================================================
# Node Implementation
# ============================================================================


class AhrefsNode(WorkflowNode):
    """Ahrefs SEO automation node (API v3)."""
    integration_type = "automation-ahrefs"
    credential_provider_labels = {"ahrefs": "Ahrefs Account"}

    # This authenticated, zero-unit endpoint proves a key is accepted. The
    # subscription name is not a unique workspace identity.
    connection_evidence = ConnectionEvidence(
        identity_operation="get_limits_and_usage",
        noun="Ahrefs account",
        identity_keys=("subscription",),
        proves="reachability",
    )

    edit_examples = [
        "Get the Domain Rating and backlink count for a competitor domain",
        "List the organic keywords a domain ranks for in the US",
        "Look up search volume and keyword difficulty for a list of keywords",
        "Find referring domains linking to my site",
        "Check my remaining Ahrefs API units before a big report",
    ]

    @classmethod
    def get_config_model(cls):
        return AhrefsNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (projects)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Optional[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name not in ("project_id", "site_audit_project_id"):
            return {"options": []}
        if not credential_data:
            return {"options": []}
        api_key = credential_data.get("api_key")
        if not isinstance(api_key, str) or not api_key.strip():
            return {"options": []}

        endpoint = "/site-audit/projects" if field_name == "site_audit_project_id" else "/management/projects"
        action = "site_audit_projects" if field_name == "site_audit_project_id" else "list_projects"
        result = await _ahrefs_request(api_key, "GET", endpoint, action_name=action)
        if result.get("status") != "success":
            # The dispatcher and connection proof must not call a rejected
            # credential an empty project list.
            raise ValueError(result.get("error") or "Ahrefs project lookup failed")
        data = result.get("data") or {}
        collection_key = "healthscores" if field_name == "site_audit_project_id" else "projects"
        projects = data.get(collection_key) if isinstance(data, dict) else None
        if not isinstance(projects, list):
            raise ValueError("Ahrefs returned an invalid project list")
        options = []
        for proj in projects:
            if not isinstance(proj, dict):
                continue
            pid = proj.get("project_id")
            name = proj.get("project_name") or f"Project {pid}"
            if pid is not None:
                options.append({"label": str(name), "value": str(pid)})
        if search:
            needle = search.strip().casefold()
            options = [option for option in options if needle in option["label"].casefold()]
        return {"options": options}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, AhrefsNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Ahrefs API key.")
        api_key = credentials.api_key

        handlers = {
            "site_overview": self._site_overview,
            "domain_rating": self._domain_rating,
            "backlinks": self._backlinks,
            "broken_backlinks": self._broken_backlinks,
            "refdomains": self._refdomains,
            "anchors": self._anchors,
            "organic_keywords": self._organic_keywords,
            "organic_competitors": self._organic_competitors,
            "top_pages": self._top_pages,
            "paid_pages": self._paid_pages,
            "best_by_external_links": self._best_by_external_links,
            "linked_domains": self._linked_domains,
            "metrics_history": self._metrics_history,
            "keywords_overview": self._keywords_overview,
            "volume_history": self._volume_history,
            "volume_by_country": self._volume_by_country,
            "matching_terms": self._matching_terms,
            "related_terms": self._related_terms,
            "search_suggestions": self._search_suggestions,
            "serp_overview": self._serp_overview,
            "batch_analysis": self._batch_analysis,
            "site_audit_projects": self._site_audit_projects,
            "site_audit_page_explorer": self._site_audit_page_explorer,
            "rank_tracker_overview": self._rank_tracker_overview,
            "list_projects": self._list_projects,
            "add_keywords": self._add_keywords,
            "add_competitors": self._add_competitors,
            "limits_and_usage": self._limits_and_usage,
            "get_limits_and_usage": self._limits_and_usage,
            "crawler_ip_ranges": self._crawler_ip_ranges,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_key)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Site Explorer handlers
    # ------------------------------------------------------------------
    async def _site_overview(self, c: AhrefsSiteOverviewConfig, api_key: str) -> Dict[str, Any]:
        params = {"target": c.target, "mode": c.mode, "protocol": c.protocol, "date": c.date}
        combined: Dict[str, Any] = {}
        timing = 0.0
        for endpoint, request_params in (
            ("/site-explorer/metrics", params),
            ("/site-explorer/domain-rating", {"target": c.target, "date": c.date}),
            ("/site-explorer/backlinks-stats", params),
        ):
            result = await _ahrefs_request(
                api_key, "GET", endpoint, params=request_params, action_name="site_overview"
            )
            if result.get("status") != "success":
                return result
            data = result["data"]
            if not isinstance(data, dict):
                return {"status": "error", "action": "site_overview", "error": "Ahrefs returned an invalid overview response"}
            for key, value in data.items():
                if isinstance(value, dict) and isinstance(combined.get(key), dict):
                    combined[key].update(value)
                else:
                    combined[key] = value
            timing += result.get("timing_ms", {}).get("api_request", 0)
        return {"status": "success", "action": "site_overview", "data": combined,
                "status_code": 200, "timing_ms": {"api_request": timing}}

    async def _domain_rating(self, c: AhrefsDomainRatingConfig, api_key: str) -> Dict[str, Any]:
        params = {"target": c.target, "date": c.date}
        return await _ahrefs_request(
            api_key, "GET", "/site-explorer/domain-rating", params=params, action_name="domain_rating"
        )

    async def _backlinks(self, c: AhrefsBacklinksConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "target": c.target,
            "mode": c.mode,
            "limit": c.limit,
            "select": c.select,
            "order_by": c.order_by,
        }
        return await _ahrefs_request(
            api_key, "GET", "/site-explorer/all-backlinks", params=params, action_name="backlinks"
        )

    async def _broken_backlinks(self, c: AhrefsBrokenBacklinksConfig, api_key: str) -> Dict[str, Any]:
        params = {"target": c.target, "mode": c.mode, "limit": c.limit, "select": c.select}
        return await _ahrefs_request(
            api_key, "GET", "/site-explorer/broken-backlinks", params=params, action_name="broken_backlinks"
        )

    async def _refdomains(self, c: AhrefsRefDomainsConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "target": c.target,
            "mode": c.mode,
            "limit": c.limit,
            "select": c.select,
            "order_by": c.order_by,
        }
        return await _ahrefs_request(
            api_key, "GET", "/site-explorer/refdomains", params=params, action_name="refdomains"
        )

    async def _anchors(self, c: AhrefsAnchorsConfig, api_key: str) -> Dict[str, Any]:
        params = {"target": c.target, "mode": c.mode, "limit": c.limit, "select": c.select}
        return await _ahrefs_request(
            api_key, "GET", "/site-explorer/anchors", params=params, action_name="anchors"
        )

    async def _organic_keywords(self, c: AhrefsOrganicKeywordsConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "target": c.target,
            "date": c.date,
            "mode": c.mode,
            "country": c.country,
            "limit": c.limit,
            "select": c.select,
            "order_by": c.order_by,
        }
        return await _ahrefs_request(
            api_key, "GET", "/site-explorer/organic-keywords", params=params, action_name="organic_keywords"
        )

    async def _organic_competitors(self, c: AhrefsOrganicCompetitorsConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "target": c.target,
            "date": c.date,
            "mode": c.mode,
            "country": c.country,
            "limit": c.limit,
            "select": c.select,
        }
        return await _ahrefs_request(
            api_key, "GET", "/site-explorer/organic-competitors", params=params, action_name="organic_competitors"
        )

    async def _top_pages(self, c: AhrefsTopPagesConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "target": c.target,
            "date": c.date,
            "mode": c.mode,
            "country": c.country,
            "limit": c.limit,
            "select": c.select,
        }
        return await _ahrefs_request(
            api_key, "GET", "/site-explorer/top-pages", params=params, action_name="top_pages"
        )

    async def _paid_pages(self, c: AhrefsPaidPagesConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "target": c.target,
            "date": c.date,
            "mode": c.mode,
            "country": c.country,
            "limit": c.limit,
            "select": c.select,
        }
        return await _ahrefs_request(
            api_key, "GET", "/site-explorer/paid-pages", params=params, action_name="paid_pages"
        )

    async def _best_by_external_links(self, c: AhrefsBestByExternalLinksConfig, api_key: str) -> Dict[str, Any]:
        params = {"target": c.target, "mode": c.mode, "limit": c.limit, "select": c.select}
        return await _ahrefs_request(
            api_key, "GET", "/site-explorer/pages-by-backlinks", params=params, action_name="best_by_external_links"
        )

    async def _linked_domains(self, c: AhrefsLinkedDomainsConfig, api_key: str) -> Dict[str, Any]:
        params = {"target": c.target, "mode": c.mode, "limit": c.limit, "select": c.select}
        return await _ahrefs_request(
            api_key, "GET", "/site-explorer/linkeddomains", params=params, action_name="linked_domains"
        )

    async def _metrics_history(self, c: AhrefsMetricsHistoryConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "target": c.target,
            "mode": c.mode,
            "country": c.country,
            "date_from": c.date_from,
            "date_to": c.date_to,
            "select": c.select,
        }
        return await _ahrefs_request(
            api_key, "GET", "/site-explorer/metrics-history", params=params, action_name="metrics_history"
        )

    # ------------------------------------------------------------------
    # Keywords Explorer handlers
    # ------------------------------------------------------------------
    async def _keywords_overview(self, c: AhrefsKeywordsOverviewConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "keywords": ",".join(_comma_list(c.keywords)),
            "country": c.country,
            "select": c.select,
        }
        return await _ahrefs_request(
            api_key, "GET", "/keywords-explorer/overview", params=params, action_name="keywords_overview"
        )

    async def _volume_history(self, c: AhrefsVolumeHistoryConfig, api_key: str) -> Dict[str, Any]:
        params = {"keyword": c.keyword, "country": c.country}
        return await _ahrefs_request(
            api_key, "GET", "/keywords-explorer/volume-history", params=params, action_name="volume_history"
        )

    async def _volume_by_country(self, c: AhrefsVolumeByCountryConfig, api_key: str) -> Dict[str, Any]:
        params = {"keyword": c.keyword, "countries": ",".join(_comma_list(c.countries))}
        return await _ahrefs_request(
            api_key, "GET", "/keywords-explorer/volume-by-country", params=params, action_name="volume_by_country"
        )

    async def _matching_terms(self, c: AhrefsMatchingTermsConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "keywords": ",".join(_comma_list(c.keywords)),
            "country": c.country,
            "limit": c.limit,
            "select": c.select,
        }
        return await _ahrefs_request(
            api_key, "GET", "/keywords-explorer/matching-terms", params=params, action_name="matching_terms"
        )

    async def _related_terms(self, c: AhrefsRelatedTermsConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "keywords": ",".join(_comma_list(c.keywords)),
            "country": c.country,
            "limit": c.limit,
            "select": c.select,
        }
        return await _ahrefs_request(
            api_key, "GET", "/keywords-explorer/related-terms", params=params, action_name="related_terms"
        )

    async def _search_suggestions(self, c: AhrefsSearchSuggestionsConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "keywords": ",".join(_comma_list(c.keywords)),
            "country": c.country,
            "limit": c.limit,
            "select": c.select,
        }
        return await _ahrefs_request(
            api_key, "GET", "/keywords-explorer/search-suggestions", params=params, action_name="search_suggestions"
        )

    # ------------------------------------------------------------------
    # SERP / Batch handlers
    # ------------------------------------------------------------------
    async def _serp_overview(self, c: AhrefsSerpOverviewConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "keyword": c.keyword, "country": c.country, "select": c.select,
            "comparison_countries": ",".join(_comma_list(c.comparison_countries)),
            "type": ",".join(_comma_list(c.type)),
        }
        return await _ahrefs_request(
            api_key, "GET", "/serp-overview/serp-overview", params=params, action_name="serp_overview"
        )

    async def _batch_analysis(self, c: AhrefsBatchAnalysisConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "targets": [{"url": target, "mode": c.mode, "protocol": "both"}
                        for target in _comma_list(c.targets)],
            "select": _comma_list(c.select or DEFAULT_BATCH_SELECT),
        }
        return await _ahrefs_request(
            api_key, "POST", "/batch-analysis/batch-analysis", json_body=body, action_name="batch_analysis"
        )

    # ------------------------------------------------------------------
    # Site Audit handlers
    # ------------------------------------------------------------------
    async def _site_audit_projects(self, c: AhrefsSiteAuditProjectsConfig, api_key: str) -> Dict[str, Any]:
        return await _ahrefs_request(
            api_key, "GET", "/site-audit/projects", action_name="site_audit_projects"
        )

    async def _site_audit_page_explorer(self, c: AhrefsSiteAuditPageExplorerConfig, api_key: str) -> Dict[str, Any]:
        params = {"project_id": c.project_id, "limit": c.limit}
        return await _ahrefs_request(
            api_key, "GET", "/site-audit/page-explorer", params=params, action_name="site_audit_page_explorer"
        )

    # ------------------------------------------------------------------
    # Rank Tracker / Management handlers
    # ------------------------------------------------------------------
    async def _rank_tracker_overview(self, c: AhrefsRankTrackerOverviewConfig, api_key: str) -> Dict[str, Any]:
        params = {"project_id": c.project_id, "select": c.select, "device": c.device, "date": c.date}
        return await _ahrefs_request(
            api_key, "GET", "/rank-tracker/overview", params=params, action_name="rank_tracker_overview"
        )

    async def _list_projects(self, c: AhrefsListProjectsConfig, api_key: str) -> Dict[str, Any]:
        return await _ahrefs_request(
            api_key, "GET", "/management/projects", action_name="list_projects"
        )

    async def _add_keywords(self, c: AhrefsAddKeywordsConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "keywords": [{"keyword": keyword} for keyword in _comma_list(c.keywords)],
            "locations": [{"country": c.country or "us"}],
        }
        return await _ahrefs_request(
            api_key, "PUT", "/management/project-keywords", params={"project_id": c.project_id},
            json_body=body, action_name="add_keywords"
        )

    async def _add_competitors(self, c: AhrefsAddCompetitorsConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "competitors": [{"url": competitor, "mode": c.mode}
                            for competitor in _comma_list(c.competitors)],
        }
        return await _ahrefs_request(
            api_key, "POST", "/management/project-competitors", params={"project_id": c.project_id},
            json_body=body, action_name="add_competitors"
        )

    # ------------------------------------------------------------------
    # Subscription / Public handlers
    # ------------------------------------------------------------------
    async def _limits_and_usage(self, c: AhrefsLimitsAndUsageConfig, api_key: str) -> Dict[str, Any]:
        result = await _ahrefs_request(
            api_key, "GET", "/subscription-info/limits-and-usage", action_name="limits_and_usage"
        )
        if result.get("status") != "success":
            return result

        data = result.get("data")
        usage = data.get("limits_and_usage") if isinstance(data, dict) else None
        # This is the credential-connect probe. A generic JSON page or a 200
        # error envelope must never produce the green "key accepted" verdict.
        error_keys = ("error", "errors", "message")
        valid = (
            isinstance(data, dict)
            and isinstance(usage, dict)
            and isinstance(usage.get("subscription"), str)
            and bool(usage["subscription"].strip())
            and not any(key in envelope for envelope in (data, usage) for key in error_keys)
            and all(envelope.get("success") is not False for envelope in (data, usage))
            and all(envelope.get("status") not in ("error", "failed") for envelope in (data, usage))
        )
        if not valid:
            return {
                "status": "error",
                "action": "limits_and_usage",
                "error": "Ahrefs returned an invalid limits and usage response",
                "status_code": result.get("status_code"),
                "timing_ms": result.get("timing_ms", {}),
            }
        return result

    async def _crawler_ip_ranges(self, c: AhrefsCrawlerIpRangesConfig, api_key: str) -> Dict[str, Any]:
        return await _ahrefs_request(
            api_key, "GET", "/public/crawler-ip-ranges", action_name="crawler_ip_ranges"
        )
