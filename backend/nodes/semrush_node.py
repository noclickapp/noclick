"""
Semrush SEO & Marketing Analytics API automation node.

This node provides comprehensive access to Semrush API v3 for SEO, content marketing,
competitor research, PPC, and social media marketing.

Authentication: API Key (get yours at https://www.semrush.com/kb/92-api-key)

Semrush API v3:
- Analytics API: Domain, Keyword, and Backlinks reports
- Projects API: Position Tracking and Site Audit
- Trends API: Website traffic and audience insights

API Documentation:
- https://developer.semrush.com/api/v3/
"""

import logging
import httpx
from typing import Dict, Any, Optional, Union, Literal, List, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


# ============================================================================
# Semrush Credential Schemas
# ============================================================================


class SemrushAPIKeyCredential(BaseModel):
    """API Key authentication for Semrush API v3.

    Get your API key at: https://www.semrush.com/kb/92-api-key
    Navigate to: Account Menu → Subscription Info → API Units tab
    """

    credential_type: Literal["semrush_api_key"] = Field(
        "semrush_api_key", json_schema_extra={"ui:hidden": True}
    )
    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://www.semrush.com/kb/92-api-key"}
    )

    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Semrush API key for API v3 access",
        json_schema_extra={"ui:widget": "password"},
    )


# Credential type
SemrushCredential = SemrushAPIKeyCredential


# ============================================================================
# API v3 - Analytics API: Domain Reports (12 operations)
# ============================================================================


class SemrushDomainOrganicConfig(BaseModel):
    """Get organic keywords for a domain (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_domain_organic_keywords"] = Field(
        default="get_domain_organic_keywords",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Get Domain Organic Keywords",
        },
        title="Get Domain Organic Keywords",
    )
    domain: str = Field(
        ...,
        title="Domain",
        description="Target domain (e.g., example.com)",
        json_schema_extra={"placeholder": "example.com"},
    )
    database: str = Field(
        default="us",
        title="Database",
        description="Regional database code (us, uk, fr, de, etc.)",
        json_schema_extra={"placeholder": "us"},
    )
    display_limit: Optional[int] = Field(
        default=10,
        title="Limit",
        description="Number of results to return (max 10,000)",
    )
    export_columns: Optional[str] = Field(
        default="Ph,Po,Nq,Cp,Ur,Tr,Tc,Co,Nr,Td",
        title="Columns",
        description="Comma-separated column codes (Ph=Keyword, Po=Position, Nq=Volume, etc.)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class SemrushDomainAdwordsConfig(BaseModel):
    """Get paid search keywords for a domain (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_domain_paid_keywords"] = Field(
        default="get_domain_paid_keywords",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Get Domain Paid Keywords",
        },
        title="Get Domain Paid Keywords",
    )
    domain: str = Field(
        ..., title="Domain", description="Target domain (e.g., example.com)"
    )
    database: str = Field(
        default="us", title="Database", description="Regional database code"
    )
    display_limit: Optional[int] = Field(
        default=10, title="Limit", description="Number of results to return"
    )
    export_columns: Optional[str] = Field(
        default="Ph,Po,Nq,Cp,Ur,Tr,Tc,Co,Nr,Td",
        title="Columns",
        description="Comma-separated column codes",
    )


class SemrushDomainAdwordsUniqueConfig(BaseModel):
    """Get unique ad copies for a domain (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_domain_unique_ad_copies"] = Field(
        default="get_domain_unique_ad_copies",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Get Domain Unique Ad Copies",
        },
        title="Get Domain Unique Ad Copies",
    )
    domain: str = Field(..., title="Domain")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushDomainOrganicOrganicConfig(BaseModel):
    """Get organic search competitors for a domain (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_domain_organic_competitors"] = Field(
        default="get_domain_organic_competitors",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Get Domain Organic Competitors",
        },
        title="Get Domain Organic Competitors",
    )
    domain: str = Field(..., title="Domain")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")
    export_columns: Optional[str] = Field(
        default="Dn,Cr,Np,Or,Ot,Oc,Ad", title="Columns"
    )


class SemrushDomainAdwordsAdwordsConfig(BaseModel):
    """Get paid search competitors for a domain (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_domain_paid_competitors"] = Field(
        default="get_domain_paid_competitors",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Get Domain Paid Competitors",
        },
        title="Get Domain Paid Competitors",
    )
    domain: str = Field(..., title="Domain")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushDomainAdwordsHistoricalConfig(BaseModel):
    """Get historical paid keywords for a domain (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_domain_paid_keywords_historical"] = Field(
        default="get_domain_paid_keywords_historical",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Get Domain Paid Keywords Historical",
        },
        title="Get Domain Paid Keywords Historical",
    )
    domain: str = Field(..., title="Domain")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushDomainDomainsConfig(BaseModel):
    """Compare multiple domains (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["compare_domains_batch"] = Field(
        default="compare_domains_batch",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Compare Domains Batch",
        },
        title="Compare Domains Batch",
    )
    domains: str = Field(
        ...,
        title="Domains",
        description="Comma-separated list of domains to compare (max 5)",
        json_schema_extra={
            "placeholder": "example.com,competitor1.com,competitor2.com"
        },
    )
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushDomainShoppingConfig(BaseModel):
    """Get product listing ad keywords for a domain (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_domain_product_listing_keywords"] = Field(
        default="get_domain_product_listing_keywords",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Get Domain Product Listing Keywords",
        },
        title="Get Domain Product Listing Keywords",
    )
    domain: str = Field(..., title="Domain")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushDomainShoppingUniqueConfig(BaseModel):
    """Get unique product listing ads for a domain (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_domain_unique_product_listing_ads"] = Field(
        default="get_domain_unique_product_listing_ads",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Get Domain Unique Product Listing Ads",
        },
        title="Get Domain Unique Product Listing Ads",
    )
    domain: str = Field(..., title="Domain")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushDomainShoppingShoppingConfig(BaseModel):
    """Get product listing ad competitors for a domain (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_domain_product_listing_competitors"] = Field(
        default="get_domain_product_listing_competitors",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Get Domain Product Listing Competitors",
        },
        title="Get Domain Product Listing Competitors",
    )
    domain: str = Field(..., title="Domain")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushDomainOrganicUniqueConfig(BaseModel):
    """Get top organic pages for a domain (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_domain_top_organic_pages"] = Field(
        default="get_domain_top_organic_pages",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Get Domain Top Organic Pages",
        },
        title="Get Domain Top Organic Pages",
    )
    domain: str = Field(..., title="Domain")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushDomainOrganicSubdomainsConfig(BaseModel):
    """Get subdomains ranking in organic search (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_domain_subdomains_organic_ranking"] = Field(
        default="get_domain_subdomains_organic_ranking",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Get Domain Subdomains Organic Ranking",
        },
        title="Get Domain Subdomains Organic Ranking",
    )
    domain: str = Field(..., title="Domain")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


# ============================================================================
# API v3 - Analytics API: Keyword Reports (10 operations)
# ============================================================================


class SemrushPhraseAllConfig(BaseModel):
    """Get keyword overview across all databases (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_keyword_overview_all_databases"] = Field(
        default="get_keyword_overview_all_databases",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Keyword",
            "x-is-trigger": False,
            "x-display-name": "Get Keyword Overview All Databases",
        },
        title="Get Keyword Overview All Databases",
    )
    phrase: str = Field(..., title="Keyword", description="Keyword to analyze")
    export_columns: Optional[str] = Field(default="Ph,Nq,Cp,Co,Nr,Td", title="Columns")


class SemrushPhraseThisConfig(BaseModel):
    """Get keyword overview for one database (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_keyword_overview_single_database"] = Field(
        default="get_keyword_overview_single_database",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Keyword",
            "x-is-trigger": False,
            "x-display-name": "Get Keyword Overview Single Database",
        },
        title="Get Keyword Overview Single Database",
    )
    phrase: str = Field(..., title="Keyword")
    database: str = Field(default="us", title="Database")
    export_columns: Optional[str] = Field(default="Ph,Nq,Cp,Co,Nr,Td", title="Columns")


class SemrushPhraseTheseConfig(BaseModel):
    """Get batch keyword overview (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_batch_keyword_overview"] = Field(
        default="get_batch_keyword_overview",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Keyword",
            "x-is-trigger": False,
            "x-display-name": "Get Batch Keyword Overview",
        },
        title="Get Batch Keyword Overview",
    )
    phrases: str = Field(
        ...,
        title="Keywords",
        description="Comma-separated list of keywords (max 100)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    database: str = Field(default="us", title="Database")


class SemrushPhraseOrganicConfig(BaseModel):
    """Get organic search results for a keyword (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_keyword_organic_search_results"] = Field(
        default="get_keyword_organic_search_results",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Keyword",
            "x-is-trigger": False,
            "x-display-name": "Get Keyword Organic Search Results",
        },
        title="Get Keyword Organic Search Results",
    )
    phrase: str = Field(..., title="Keyword")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushPhraseAdwordsConfig(BaseModel):
    """Get paid search results for a keyword (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_keyword_paid_search_results"] = Field(
        default="get_keyword_paid_search_results",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Keyword",
            "x-is-trigger": False,
            "x-display-name": "Get Keyword Paid Search Results",
        },
        title="Get Keyword Paid Search Results",
    )
    phrase: str = Field(..., title="Keyword")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushPhraseRelatedConfig(BaseModel):
    """Get related keywords (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_related_keywords"] = Field(
        default="get_related_keywords",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Keyword",
            "x-is-trigger": False,
            "x-display-name": "Get Related Keywords",
        },
        title="Get Related Keywords",
    )
    phrase: str = Field(..., title="Keyword")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushPhraseAdwordsHistoricalConfig(BaseModel):
    """Get keyword ads history (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_keyword_ads_historical_data"] = Field(
        default="get_keyword_ads_historical_data",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Keyword",
            "x-is-trigger": False,
            "x-display-name": "Get Keyword Ads Historical Data",
        },
        title="Get Keyword Ads Historical Data",
    )
    phrase: str = Field(..., title="Keyword")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushPhraseFullsearchConfig(BaseModel):
    """Get broad match keywords (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_broad_match_keywords"] = Field(
        default="get_broad_match_keywords",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Keyword",
            "x-is-trigger": False,
            "x-display-name": "Get Broad Match Keywords",
        },
        title="Get Broad Match Keywords",
    )
    phrase: str = Field(..., title="Keyword")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushPhraseQuestionsConfig(BaseModel):
    """Get question keywords (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_question_keywords"] = Field(
        default="get_question_keywords",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Keyword",
            "x-is-trigger": False,
            "x-display-name": "Get Question Keywords",
        },
        title="Get Question Keywords",
    )
    phrase: str = Field(..., title="Keyword")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushPhraseKdiConfig(BaseModel):
    """Get keyword difficulty (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_keyword_difficulty"] = Field(
        default="get_keyword_difficulty",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Keyword",
            "x-is-trigger": False,
            "x-display-name": "Get Keyword Difficulty",
        },
        title="Get Keyword Difficulty",
    )
    phrase: str = Field(..., title="Keyword")
    database: str = Field(default="us", title="Database")
    export_columns: Optional[str] = Field(default="Ph,Kd", title="Columns")


# ============================================================================
# API v3 - Analytics API: Backlinks Reports (15 operations)
# ============================================================================


class SemrushBacklinksOverviewConfig(BaseModel):
    """Get backlinks overview for a domain (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_backlinks_overview"] = Field(
        default="get_backlinks_overview",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Backlink",
            "x-is-trigger": False,
            "x-display-name": "Get Backlinks Overview",
        },
        title="Get Backlinks Overview",
    )
    target: str = Field(..., title="Target", description="Domain or URL to analyze")
    target_type: str = Field(
        default="root_domain",
        title="Target Type",
        description="Type of target: root_domain, domain, subdomain, or url",
    )
    export_columns: Optional[str] = Field(
        default="ascore,total,domains,urls,ips,follows,nofollows,forms,texts,images",
        title="Columns",
    )


class SemrushBacklinksConfig(BaseModel):
    """Get backlinks list for a domain (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_backlinks_list"] = Field(
        default="get_backlinks_list",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Backlink",
            "x-is-trigger": False,
            "x-display-name": "Get Backlinks List",
        },
        title="Get Backlinks List",
    )
    target: str = Field(..., title="Target")
    target_type: str = Field(default="root_domain", title="Target Type")
    display_limit: Optional[int] = Field(default=10, title="Limit")
    export_columns: Optional[str] = Field(
        default="source_url,target_url,anchor,external_links,internal_links,source_title,last_seen,first_seen",
        title="Columns",
    )


class SemrushBacklinksRefdomainsConfig(BaseModel):
    """Get referring domains (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_referring_domains"] = Field(
        default="get_referring_domains",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Backlink",
            "x-is-trigger": False,
            "x-display-name": "Get Referring Domains",
        },
        title="Get Referring Domains",
    )
    target: str = Field(..., title="Target")
    target_type: str = Field(default="root_domain", title="Target Type")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushBacklinksRefipsConfig(BaseModel):
    """Get referring IPs (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_referring_ip_addresses"] = Field(
        default="get_referring_ip_addresses",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Backlink",
            "x-is-trigger": False,
            "x-display-name": "Get Referring Ip Addresses",
        },
        title="Get Referring Ip Addresses",
    )
    target: str = Field(..., title="Target")
    target_type: str = Field(default="root_domain", title="Target Type")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushBacklinksTldConfig(BaseModel):
    """Get backlinks by TLD distribution (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_backlinks_by_tld"] = Field(
        default="get_backlinks_by_tld",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Backlink",
            "x-is-trigger": False,
            "x-display-name": "Get Backlinks by Tld",
        },
        title="Get Backlinks by Tld",
    )
    target: str = Field(..., title="Target")
    target_type: str = Field(default="root_domain", title="Target Type")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushBacklinksGeoConfig(BaseModel):
    """Get backlinks by country (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_backlinks_by_country"] = Field(
        default="get_backlinks_by_country",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Backlink",
            "x-is-trigger": False,
            "x-display-name": "Get Backlinks by Country",
        },
        title="Get Backlinks by Country",
    )
    target: str = Field(..., title="Target")
    target_type: str = Field(default="root_domain", title="Target Type")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushBacklinksAnchorsConfig(BaseModel):
    """Get anchor text distribution (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_backlink_anchor_distribution"] = Field(
        default="get_backlink_anchor_distribution",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Backlink",
            "x-is-trigger": False,
            "x-display-name": "Get Backlink Anchor Distribution",
        },
        title="Get Backlink Anchor Distribution",
    )
    target: str = Field(..., title="Target")
    target_type: str = Field(default="root_domain", title="Target Type")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushBacklinksPagesConfig(BaseModel):
    """Get indexed pages with backlinks (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_pages_with_backlinks"] = Field(
        default="get_pages_with_backlinks",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Backlink",
            "x-is-trigger": False,
            "x-display-name": "Get Pages with Backlinks",
        },
        title="Get Pages with Backlinks",
    )
    target: str = Field(..., title="Target")
    target_type: str = Field(default="root_domain", title="Target Type")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushBacklinksCompetitorsConfig(BaseModel):
    """Get backlink competitors (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_backlink_competitors"] = Field(
        default="get_backlink_competitors",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Backlink",
            "x-is-trigger": False,
            "x-display-name": "Get Backlink Competitors",
        },
        title="Get Backlink Competitors",
    )
    target: str = Field(..., title="Target")
    target_type: str = Field(default="root_domain", title="Target Type")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushBacklinksMatrixConfig(BaseModel):
    """Compare backlinks between domains (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["compare_backlinks_between_domains"] = Field(
        default="compare_backlinks_between_domains",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Backlink",
            "x-is-trigger": False,
            "x-display-name": "Compare Backlinks Between Domains",
        },
        title="Compare Backlinks Between Domains",
    )
    targets: str = Field(
        ...,
        title="Targets",
        description="Comma-separated list of domains to compare",
        json_schema_extra={"placeholder": "example.com,competitor1.com"},
    )
    target_type: str = Field(default="root_domain", title="Target Type")


class SemrushBacklinksComparisonConfig(BaseModel):
    """Batch compare backlink profiles (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["compare_backlink_profiles_batch"] = Field(
        default="compare_backlink_profiles_batch",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Backlink",
            "x-is-trigger": False,
            "x-display-name": "Compare Backlink Profiles Batch",
        },
        title="Compare Backlink Profiles Batch",
    )
    targets: str = Field(
        ..., title="Targets", description="Comma-separated list (max 200)"
    )
    target_type: str = Field(default="root_domain", title="Target Type")


class SemrushBacklinksAscoreProfileConfig(BaseModel):
    """Get authority score distribution (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_authority_score_distribution"] = Field(
        default="get_authority_score_distribution",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Backlink",
            "x-is-trigger": False,
            "x-display-name": "Get Authority Score Distribution",
        },
        title="Get Authority Score Distribution",
    )
    target: str = Field(..., title="Target")
    target_type: str = Field(default="root_domain", title="Target Type")


class SemrushBacklinksCategoriesProfileConfig(BaseModel):
    """Get referring domain categories profile (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_referring_domain_categories"] = Field(
        default="get_referring_domain_categories",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Backlink",
            "x-is-trigger": False,
            "x-display-name": "Get Referring Domain Categories",
        },
        title="Get Referring Domain Categories",
    )
    target: str = Field(..., title="Target")
    target_type: str = Field(default="root_domain", title="Target Type")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushBacklinksCategoriesConfig(BaseModel):
    """Get target domain categories (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_target_domain_categories"] = Field(
        default="get_target_domain_categories",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Backlink",
            "x-is-trigger": False,
            "x-display-name": "Get Target Domain Categories",
        },
        title="Get Target Domain Categories",
    )
    target: str = Field(..., title="Target")
    target_type: str = Field(default="root_domain", title="Target Type")


class SemrushBacklinksHistoricalConfig(BaseModel):
    """Get backlinks historical data (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_backlinks_historical_data"] = Field(
        default="get_backlinks_historical_data",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Backlink",
            "x-is-trigger": False,
            "x-display-name": "Get Backlinks Historical Data",
        },
        title="Get Backlinks Historical Data",
    )
    target: str = Field(..., title="Target")
    target_type: str = Field(default="root_domain", title="Target Type")
    display_limit: Optional[int] = Field(default=10, title="Limit")


# ============================================================================
# API v3 - Analytics API: Overview Reports (5 operations)
# ============================================================================


class SemrushDomainRanksConfig(BaseModel):
    """Get domain overview across all databases (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_domain_overview_all_databases"] = Field(
        default="get_domain_overview_all_databases",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Get Domain Overview All Databases",
        },
        title="Get Domain Overview All Databases",
    )
    domain: str = Field(..., title="Domain", description="Target domain")
    export_columns: Optional[str] = Field(
        default="Rk,Or,Ot,Oc,Ad,At,Ac", title="Columns"
    )


class SemrushDomainRankConfig(BaseModel):
    """Get domain overview for one database (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_domain_overview_single_database"] = Field(
        default="get_domain_overview_single_database",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Get Domain Overview Single Database",
        },
        title="Get Domain Overview Single Database",
    )
    domain: str = Field(..., title="Domain")
    database: str = Field(default="us", title="Database")
    export_columns: Optional[str] = Field(
        default="Rk,Or,Ot,Oc,Ad,At,Ac", title="Columns"
    )


class SemrushDomainRankHistoryConfig(BaseModel):
    """Get domain rank history (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_domain_rank_history"] = Field(
        default="get_domain_rank_history",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Get Domain Rank History",
        },
        title="Get Domain Rank History",
    )
    domain: str = Field(..., title="Domain")
    database: str = Field(default="us", title="Database")
    display_daily: Optional[bool] = Field(
        default=False,
        title="Display Daily",
        description="Show daily rankings for last 31 days (True) or monthly historical data (False)",
    )


class SemrushRankDifferenceConfig(BaseModel):
    """Get winners and losers report (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_winners_and_losers_report"] = Field(
        default="get_winners_and_losers_report",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Rank Report",
            "x-is-trigger": False,
            "x-display-name": "Get Winners and Losers Report",
        },
        title="Get Winners and Losers Report",
    )
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")
    display_filter: Optional[str] = Field(
        default=None,
        title="Filter",
        description="Filter by '+' (gainers) or '-' (losers)",
    )


class SemrushRankConfig(BaseModel):
    """Get Semrush Rank report (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_semrush_rank_report"] = Field(
        default="get_semrush_rank_report",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Rank Report",
            "x-is-trigger": False,
            "x-display-name": "Get Semrush Rank Report",
        },
        title="Get Semrush Rank Report",
    )
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


# ============================================================================
# API v3 - Analytics API: Subdomain Reports (7 operations)
# ============================================================================


class SemrushSubdomainRankConfig(BaseModel):
    """Get subdomain overview for one database (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_subdomain_overview_single_database"] = Field(
        default="get_subdomain_overview_single_database",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subdomain",
            "x-is-trigger": False,
            "x-display-name": "Get Subdomain Overview Single Database",
        },
        title="Get Subdomain Overview Single Database",
    )
    domain: str = Field(
        ..., title="Subdomain", description="Full subdomain (e.g., blog.example.com)"
    )
    database: str = Field(default="us", title="Database")


class SemrushSubdomainRanksConfig(BaseModel):
    """Get subdomain overview across all databases (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_subdomain_overview_all_databases"] = Field(
        default="get_subdomain_overview_all_databases",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subdomain",
            "x-is-trigger": False,
            "x-display-name": "Get Subdomain Overview All Databases",
        },
        title="Get Subdomain Overview All Databases",
    )
    domain: str = Field(..., title="Subdomain")


class SemrushSubdomainRankHistoryConfig(BaseModel):
    """Get subdomain rank history (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_subdomain_rank_history"] = Field(
        default="get_subdomain_rank_history",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subdomain",
            "x-is-trigger": False,
            "x-display-name": "Get Subdomain Rank History",
        },
        title="Get Subdomain Rank History",
    )
    domain: str = Field(..., title="Subdomain")
    database: str = Field(default="us", title="Database")
    display_daily: Optional[bool] = Field(default=False, title="Display Daily")


class SemrushSubdomainOrganicConfig(BaseModel):
    """Get subdomain organic keywords (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_subdomain_organic_keywords"] = Field(
        default="get_subdomain_organic_keywords",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subdomain",
            "x-is-trigger": False,
            "x-display-name": "Get Subdomain Organic Keywords",
        },
        title="Get Subdomain Organic Keywords",
    )
    domain: str = Field(..., title="Subdomain")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushSubdomainAdwordsConfig(BaseModel):
    """Get subdomain paid keywords (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_subdomain_paid_keywords"] = Field(
        default="get_subdomain_paid_keywords",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subdomain",
            "x-is-trigger": False,
            "x-display-name": "Get Subdomain Paid Keywords",
        },
        title="Get Subdomain Paid Keywords",
    )
    domain: str = Field(..., title="Subdomain")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushSubdomainOrganicUniqueConfig(BaseModel):
    """Get subdomain organic pages (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_subdomain_top_organic_pages"] = Field(
        default="get_subdomain_top_organic_pages",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subdomain",
            "x-is-trigger": False,
            "x-display-name": "Get Subdomain Top Organic Pages",
        },
        title="Get Subdomain Top Organic Pages",
    )
    domain: str = Field(..., title="Subdomain")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushSubdomainAdwordsUniqueConfig(BaseModel):
    """Get subdomain ad copies (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_subdomain_unique_ad_copies"] = Field(
        default="get_subdomain_unique_ad_copies",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subdomain",
            "x-is-trigger": False,
            "x-display-name": "Get Subdomain Unique Ad Copies",
        },
        title="Get Subdomain Unique Ad Copies",
    )
    domain: str = Field(..., title="Subdomain")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


# ============================================================================
# API v3 - Analytics API: Subfolder Reports (7 operations)
# ============================================================================


class SemrushSubfolderRankConfig(BaseModel):
    """Get subfolder overview for one database (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_subfolder_overview_single_database"] = Field(
        default="get_subfolder_overview_single_database",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subfolder",
            "x-is-trigger": False,
            "x-display-name": "Get Subfolder Overview Single Database",
        },
        title="Get Subfolder Overview Single Database",
    )
    url: str = Field(
        ...,
        title="Subfolder URL",
        description="Full subfolder URL (e.g., example.com/blog/)",
    )
    database: str = Field(default="us", title="Database")


class SemrushSubfolderRanksConfig(BaseModel):
    """Get subfolder overview across all databases (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_subfolder_overview_all_databases"] = Field(
        default="get_subfolder_overview_all_databases",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subfolder",
            "x-is-trigger": False,
            "x-display-name": "Get Subfolder Overview All Databases",
        },
        title="Get Subfolder Overview All Databases",
    )
    url: str = Field(..., title="Subfolder URL")


class SemrushSubfolderRankHistoryConfig(BaseModel):
    """Get subfolder rank history (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_subfolder_rank_history"] = Field(
        default="get_subfolder_rank_history",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subfolder",
            "x-is-trigger": False,
            "x-display-name": "Get Subfolder Rank History",
        },
        title="Get Subfolder Rank History",
    )
    url: str = Field(..., title="Subfolder URL")
    database: str = Field(default="us", title="Database")
    display_daily: Optional[bool] = Field(default=False, title="Display Daily")


class SemrushSubfolderOrganicConfig(BaseModel):
    """Get subfolder organic keywords (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_subfolder_organic_keywords"] = Field(
        default="get_subfolder_organic_keywords",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subfolder",
            "x-is-trigger": False,
            "x-display-name": "Get Subfolder Organic Keywords",
        },
        title="Get Subfolder Organic Keywords",
    )
    url: str = Field(..., title="Subfolder URL")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushSubfolderAdwordsConfig(BaseModel):
    """Get subfolder paid keywords (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_subfolder_paid_keywords"] = Field(
        default="get_subfolder_paid_keywords",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subfolder",
            "x-is-trigger": False,
            "x-display-name": "Get Subfolder Paid Keywords",
        },
        title="Get Subfolder Paid Keywords",
    )
    url: str = Field(..., title="Subfolder URL")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushSubfolderOrganicUniqueConfig(BaseModel):
    """Get subfolder organic pages (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_subfolder_top_organic_pages"] = Field(
        default="get_subfolder_top_organic_pages",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subfolder",
            "x-is-trigger": False,
            "x-display-name": "Get Subfolder Top Organic Pages",
        },
        title="Get Subfolder Top Organic Pages",
    )
    url: str = Field(..., title="Subfolder URL")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushSubfolderAdwordsUniqueConfig(BaseModel):
    """Get subfolder ad copies (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_subfolder_unique_ad_copies"] = Field(
        default="get_subfolder_unique_ad_copies",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subfolder",
            "x-is-trigger": False,
            "x-display-name": "Get Subfolder Unique Ad Copies",
        },
        title="Get Subfolder Unique Ad Copies",
    )
    url: str = Field(..., title="Subfolder URL")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


# ============================================================================
# API v3 - Analytics API: URL Reports (5 operations)
# ============================================================================


class SemrushUrlRankConfig(BaseModel):
    """Get URL overview for one database (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_url_overview_single_database"] = Field(
        default="get_url_overview_single_database",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "URL",
            "x-is-trigger": False,
            "x-display-name": "Get Url Overview Single Database",
        },
        title="Get Url Overview Single Database",
    )
    url: str = Field(..., title="URL", description="Full URL to analyze")
    database: str = Field(default="us", title="Database")


class SemrushUrlRanksConfig(BaseModel):
    """Get URL overview across all databases (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_url_overview_all_databases"] = Field(
        default="get_url_overview_all_databases",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "URL",
            "x-is-trigger": False,
            "x-display-name": "Get Url Overview All Databases",
        },
        title="Get Url Overview All Databases",
    )
    url: str = Field(..., title="URL")


class SemrushUrlRankHistoryConfig(BaseModel):
    """Get URL rank history (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_url_rank_history"] = Field(
        default="get_url_rank_history",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "URL",
            "x-is-trigger": False,
            "x-display-name": "Get Url Rank History",
        },
        title="Get Url Rank History",
    )
    url: str = Field(..., title="URL")
    database: str = Field(default="us", title="Database")
    display_daily: Optional[bool] = Field(default=False, title="Display Daily")


class SemrushUrlOrganicConfig(BaseModel):
    """Get URL organic keywords (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_url_organic_keywords"] = Field(
        default="get_url_organic_keywords",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "URL",
            "x-is-trigger": False,
            "x-display-name": "Get Url Organic Keywords",
        },
        title="Get Url Organic Keywords",
    )
    url: str = Field(..., title="URL")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushUrlAdwordsConfig(BaseModel):
    """Get URL paid keywords (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_url_paid_keywords"] = Field(
        default="get_url_paid_keywords",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "URL",
            "x-is-trigger": False,
            "x-display-name": "Get Url Paid Keywords",
        },
        title="Get Url Paid Keywords",
    )
    url: str = Field(..., title="URL")
    database: str = Field(default="us", title="Database")
    display_limit: Optional[int] = Field(default=10, title="Limit")


# ============================================================================
# API v3 - Trends API: Traffic & Audience Reports (13 operations)
# ============================================================================


class SemrushTrafficSummaryConfig(BaseModel):
    """Get traffic summary for domains (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_traffic_summary_for_domains"] = Field(
        default="get_traffic_summary_for_domains",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Traffic",
            "x-is-trigger": False,
            "x-display-name": "Get Traffic Summary for Domains",
        },
        title="Get Traffic Summary for Domains",
    )
    targets: str = Field(
        ...,
        title="Domains",
        description="Comma-separated list of domains (max 200)",
        json_schema_extra={"placeholder": "example.com,competitor.com"},
    )
    display_limit: Optional[int] = Field(default=10, title="Limit")
    country: Optional[str] = Field(
        default=None,
        title="Country Code",
        description="2-letter country code (e.g., us, uk)",
    )
    device_type: Optional[str] = Field(
        default=None,
        title="Device Type",
        description="Filter by device: desktop, mobile, or both",
    )


class SemrushTrafficDailyConfig(BaseModel):
    """Get daily traffic breakdown (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_daily_traffic_breakdown"] = Field(
        default="get_daily_traffic_breakdown",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Traffic",
            "x-is-trigger": False,
            "x-display-name": "Get Daily Traffic Breakdown",
        },
        title="Get Daily Traffic Breakdown",
    )
    target: str = Field(..., title="Domain")
    country: Optional[str] = Field(default=None, title="Country Code")
    device_type: Optional[str] = Field(default=None, title="Device Type")


class SemrushTrafficWeeklyConfig(BaseModel):
    """Get weekly traffic breakdown (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_weekly_traffic_breakdown"] = Field(
        default="get_weekly_traffic_breakdown",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Traffic",
            "x-is-trigger": False,
            "x-display-name": "Get Weekly Traffic Breakdown",
        },
        title="Get Weekly Traffic Breakdown",
    )
    target: str = Field(..., title="Domain")
    country: Optional[str] = Field(default=None, title="Country Code")
    device_type: Optional[str] = Field(default=None, title="Device Type")


class SemrushPurchaseConversionConfig(BaseModel):
    """Get purchase conversion rates (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_purchase_conversion_rates"] = Field(
        default="get_purchase_conversion_rates",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Conversion",
            "x-is-trigger": False,
            "x-display-name": "Get Purchase Conversion Rates",
        },
        title="Get Purchase Conversion Rates",
    )
    target: str = Field(..., title="Domain")


class SemrushIndustryCategoriesConfig(BaseModel):
    """Get domains by industry category (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_domains_by_industry_category"] = Field(
        default="get_domains_by_industry_category",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Industry",
            "x-is-trigger": False,
            "x-display-name": "Get Domains by Industry Category",
        },
        title="Get Domains by Industry Category",
    )
    category: str = Field(..., title="Category", description="Industry category name")
    country: Optional[str] = Field(default="us", title="Country Code")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushTrafficSourcesConfig(BaseModel):
    """Get traffic sources breakdown (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_traffic_sources_breakdown"] = Field(
        default="get_traffic_sources_breakdown",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Traffic",
            "x-is-trigger": False,
            "x-display-name": "Get Traffic Sources Breakdown",
        },
        title="Get Traffic Sources Breakdown",
    )
    target: str = Field(..., title="Domain")
    country: Optional[str] = Field(default=None, title="Country Code")
    device_type: Optional[str] = Field(default=None, title="Device Type")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushTrafficDestinationsConfig(BaseModel):
    """Get traffic destinations (where users go next) (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_traffic_destinations"] = Field(
        default="get_traffic_destinations",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Traffic",
            "x-is-trigger": False,
            "x-display-name": "Get Traffic Destinations",
        },
        title="Get Traffic Destinations",
    )
    target: str = Field(..., title="Domain")
    country: Optional[str] = Field(default=None, title="Country Code")
    device_type: Optional[str] = Field(default=None, title="Device Type")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushGeoDistributionConfig(BaseModel):
    """Get geographic traffic distribution (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_geographic_traffic_distribution"] = Field(
        default="get_geographic_traffic_distribution",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Traffic",
            "x-is-trigger": False,
            "x-display-name": "Get Geographic Traffic Distribution",
        },
        title="Get Geographic Traffic Distribution",
    )
    target: str = Field(..., title="Domain")
    device_type: Optional[str] = Field(default=None, title="Device Type")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushSubdomainsTrafficConfig(BaseModel):
    """Get traffic to subdomains (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_subdomain_traffic"] = Field(
        default="get_subdomain_traffic",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subdomain",
            "x-is-trigger": False,
            "x-display-name": "Get Subdomain Traffic",
        },
        title="Get Subdomain Traffic",
    )
    target: str = Field(..., title="Domain")
    country: Optional[str] = Field(default=None, title="Country Code")
    device_type: Optional[str] = Field(default=None, title="Device Type")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushTopPagesConfig(BaseModel):
    """Get top pages by traffic (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_top_pages_by_traffic"] = Field(
        default="get_top_pages_by_traffic",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Traffic",
            "x-is-trigger": False,
            "x-display-name": "Get Top Pages by Traffic",
        },
        title="Get Top Pages by Traffic",
    )
    target: str = Field(..., title="Domain")
    country: Optional[str] = Field(default=None, title="Country Code")
    device_type: Optional[str] = Field(default=None, title="Device Type")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushTrafficRankConfig(BaseModel):
    """Get traffic rank for domains (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_traffic_rank_for_domains"] = Field(
        default="get_traffic_rank_for_domains",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Traffic",
            "x-is-trigger": False,
            "x-display-name": "Get Traffic Rank for Domains",
        },
        title="Get Traffic Rank for Domains",
    )
    targets: str = Field(
        ..., title="Domains", description="Comma-separated list (max 200)"
    )
    country: Optional[str] = Field(default=None, title="Country Code")
    device_type: Optional[str] = Field(default=None, title="Device Type")


class SemrushAudienceInsightsConfig(BaseModel):
    """Get audience demographics and interests (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_audience_demographics"] = Field(
        default="get_audience_demographics",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Audience",
            "x-is-trigger": False,
            "x-display-name": "Get Audience Demographics",
        },
        title="Get Audience Demographics",
    )
    target: str = Field(..., title="Domain")
    country: Optional[str] = Field(default="us", title="Country Code")


class SemrushSubfoldersTrafficConfig(BaseModel):
    """Get traffic to subfolders (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_subfolder_traffic"] = Field(
        default="get_subfolder_traffic",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subfolder",
            "x-is-trigger": False,
            "x-display-name": "Get Subfolder Traffic",
        },
        title="Get Subfolder Traffic",
    )
    target: str = Field(..., title="Domain")
    country: Optional[str] = Field(default=None, title="Country Code")
    device_type: Optional[str] = Field(default=None, title="Device Type")
    display_limit: Optional[int] = Field(default=10, title="Limit")


# ============================================================================
# API v3 - Projects API: Position Tracking (16 operations)
# ============================================================================


class SemrushPTCampaignListConfig(BaseModel):
    """List all position tracking campaigns (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_position_tracking_campaigns"] = Field(
        default="list_position_tracking_campaigns",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Position Tracking",
            "x-is-trigger": False,
            "x-display-name": "List Position Tracking Campaigns",
        },
        title="List Position Tracking Campaigns",
    )
    project_id: str = Field(..., title="Project ID", description="Semrush project ID")


class SemrushPTCreateCampaignConfig(BaseModel):
    """Create position tracking campaign (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_position_tracking_campaign"] = Field(
        default="create_position_tracking_campaign",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Position Tracking",
            "x-is-trigger": False,
            "x-display-name": "Create Position Tracking Campaign",
        },
        title="Create Position Tracking Campaign",
    )
    project_id: str = Field(..., title="Project ID")
    domain: str = Field(..., title="Domain to Track")
    location_id: str = Field(..., title="Location ID")
    device: str = Field(
        default="desktop", title="Device", description="desktop or mobile"
    )
    keywords: str = Field(
        ...,
        title="Keywords",
        description="Comma-separated list of keywords to track",
        json_schema_extra={"ui:widget": "textarea"},
    )


class SemrushPTAddKeywordsConfig(BaseModel):
    """Add keywords to campaign (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_keywords_to_tracking_campaign"] = Field(
        default="add_keywords_to_tracking_campaign",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Position Tracking",
            "x-is-trigger": False,
            "x-display-name": "Add Keywords to Tracking Campaign",
        },
        title="Add Keywords to Tracking Campaign",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    keywords: str = Field(
        ...,
        title="Keywords",
        description="Comma-separated list",
        json_schema_extra={"ui:widget": "textarea"},
    )


class SemrushPTRemoveKeywordsConfig(BaseModel):
    """Remove keywords from campaign (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_keywords_from_tracking_campaign"] = Field(
        default="remove_keywords_from_tracking_campaign",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Position Tracking",
            "x-is-trigger": False,
            "x-display-name": "Remove Keywords from Tracking Campaign",
        },
        title="Remove Keywords from Tracking Campaign",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    keyword_ids: str = Field(
        ...,
        title="Keyword IDs",
        description="Comma-separated list of keyword IDs to remove",
    )


class SemrushPTAddTagsConfig(BaseModel):
    """Add tags to keywords (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_tags_to_tracked_keywords"] = Field(
        default="add_tags_to_tracked_keywords",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Position Tracking",
            "x-is-trigger": False,
            "x-display-name": "Add Tags to Tracked Keywords",
        },
        title="Add Tags to Tracked Keywords",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    keyword_ids: str = Field(..., title="Keyword IDs (comma-separated)")
    tags: str = Field(..., title="Tags (comma-separated)")


class SemrushPTRemoveTagsConfig(BaseModel):
    """Remove tags from keywords (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_tags_from_tracked_keywords"] = Field(
        default="remove_tags_from_tracked_keywords",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Position Tracking",
            "x-is-trigger": False,
            "x-display-name": "Remove Tags from Tracked Keywords",
        },
        title="Remove Tags from Tracked Keywords",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    keyword_ids: str = Field(..., title="Keyword IDs")
    tags: str = Field(..., title="Tags")


class SemrushPTAddCompetitorsConfig(BaseModel):
    """Add competitors to campaign (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_competitors_to_tracking_campaign"] = Field(
        default="add_competitors_to_tracking_campaign",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Position Tracking",
            "x-is-trigger": False,
            "x-display-name": "Add Competitors to Tracking Campaign",
        },
        title="Add Competitors to Tracking Campaign",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    competitors: str = Field(
        ...,
        title="Competitor Domains",
        description="Comma-separated list (max 20 total)",
    )


class SemrushPTRemoveCompetitorsConfig(BaseModel):
    """Remove competitors from campaign (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_competitors_from_tracking_campaign"] = Field(
        default="remove_competitors_from_tracking_campaign",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Position Tracking",
            "x-is-trigger": False,
            "x-display-name": "Remove Competitors from Tracking Campaign",
        },
        title="Remove Competitors from Tracking Campaign",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    competitors: str = Field(..., title="Competitor Domains")


class SemrushPTLocationSearchConfig(BaseModel):
    """Search for tracking locations (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_tracking_locations"] = Field(
        default="search_tracking_locations",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Position Tracking",
            "x-is-trigger": False,
            "x-display-name": "Search Tracking Locations",
        },
        title="Search Tracking Locations",
    )
    query: str = Field(
        ..., title="Search Query", description="Search for city/region name"
    )


class SemrushPTCampaignDatesConfig(BaseModel):
    """Get campaign harvest dates (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_tracking_campaign_harvest_dates"] = Field(
        default="get_tracking_campaign_harvest_dates",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Position Tracking",
            "x-is-trigger": False,
            "x-display-name": "Get Tracking Campaign Harvest Dates",
        },
        title="Get Tracking Campaign Harvest Dates",
    )
    campaign_id: str = Field(..., title="Campaign ID")


class SemrushPTOrganicOverviewConfig(BaseModel):
    """Get organic overview report (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_organic_tracking_overview"] = Field(
        default="get_organic_tracking_overview",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Position Tracking",
            "x-is-trigger": False,
            "x-display-name": "Get Organic Tracking Overview",
        },
        title="Get Organic Tracking Overview",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    display_date: Optional[str] = Field(
        default=None, title="Date", description="Date in YYYYMMDD format"
    )


class SemrushPTAdwordsOverviewConfig(BaseModel):
    """Get paid search overview report (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_paid_search_tracking_overview"] = Field(
        default="get_paid_search_tracking_overview",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Position Tracking",
            "x-is-trigger": False,
            "x-display-name": "Get Paid Search Tracking Overview",
        },
        title="Get Paid Search Tracking Overview",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    display_date: Optional[str] = Field(default=None, title="Date (YYYYMMDD)")


class SemrushPTOrganicPositionsConfig(BaseModel):
    """Get organic keyword positions (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_organic_keyword_positions"] = Field(
        default="get_organic_keyword_positions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Position Tracking",
            "x-is-trigger": False,
            "x-display-name": "Get Organic Keyword Positions",
        },
        title="Get Organic Keyword Positions",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    display_date: Optional[str] = Field(default=None, title="Date (YYYYMMDD)")
    display_limit: Optional[int] = Field(default=100, title="Limit")


class SemrushPTAdwordsPositionsConfig(BaseModel):
    """Get paid search keyword positions (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_paid_search_keyword_positions"] = Field(
        default="get_paid_search_keyword_positions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Position Tracking",
            "x-is-trigger": False,
            "x-display-name": "Get Paid Search Keyword Positions",
        },
        title="Get Paid Search Keyword Positions",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    display_date: Optional[str] = Field(default=None, title="Date (YYYYMMDD)")
    display_limit: Optional[int] = Field(default=100, title="Limit")


class SemrushPTEnableNotificationsConfig(BaseModel):
    """Enable email notifications for campaign (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["enable_campaign_email_notifications"] = Field(
        default="enable_campaign_email_notifications",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Position Tracking",
            "x-is-trigger": False,
            "x-display-name": "Enable Campaign Email Notifications",
        },
        title="Enable Campaign Email Notifications",
    )
    campaign_id: str = Field(..., title="Campaign ID")


class SemrushPTDisableNotificationsConfig(BaseModel):
    """Disable email notifications for campaign (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["disable_campaign_email_notifications"] = Field(
        default="disable_campaign_email_notifications",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Position Tracking",
            "x-is-trigger": False,
            "x-display-name": "Disable Campaign Email Notifications",
        },
        title="Disable Campaign Email Notifications",
    )
    campaign_id: str = Field(..., title="Campaign ID")


# ============================================================================
# API v3 - Projects API: Site Audit (11 operations)
# ============================================================================


class SemrushSAEnableConfig(BaseModel):
    """Enable Site Audit for a project (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["enable_site_audit_for_project"] = Field(
        default="enable_site_audit_for_project",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Site Audit",
            "x-is-trigger": False,
            "x-display-name": "Enable Site Audit for Project",
        },
        title="Enable Site Audit for Project",
    )
    project_id: str = Field(..., title="Project ID")
    domain: str = Field(..., title="Domain to Audit")
    crawl_subdomains: Optional[bool] = Field(default=False, title="Crawl Subdomains")
    max_pages: Optional[int] = Field(default=100, title="Max Pages to Crawl")


class SemrushSAEditCampaignConfig(BaseModel):
    """Edit Site Audit campaign settings (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_site_audit_campaign"] = Field(
        default="update_site_audit_campaign",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Site Audit",
            "x-is-trigger": False,
            "x-display-name": "Update Site Audit Campaign",
        },
        title="Update Site Audit Campaign",
    )
    project_id: str = Field(..., title="Project ID")
    max_pages: Optional[int] = Field(default=None, title="Max Pages")
    crawl_subdomains: Optional[bool] = Field(default=None, title="Crawl Subdomains")


class SemrushSAGetSnapshotsConfig(BaseModel):
    """Get list of audit snapshots (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_audit_snapshots"] = Field(
        default="list_audit_snapshots",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Site Audit",
            "x-is-trigger": False,
            "x-display-name": "List Audit Snapshots",
        },
        title="List Audit Snapshots",
    )
    project_id: str = Field(..., title="Project ID")


class SemrushSALaunchAuditConfig(BaseModel):
    """Launch a new site audit (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["launch_site_audit"] = Field(
        default="launch_site_audit",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Site Audit",
            "x-is-trigger": False,
            "x-display-name": "Launch Site Audit",
        },
        title="Launch Site Audit",
    )
    project_id: str = Field(..., title="Project ID")


class SemrushSAGetCampaignInfoConfig(BaseModel):
    """Get campaign info (latest audit results summary) (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_site_audit_campaign_info"] = Field(
        default="get_site_audit_campaign_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Site Audit",
            "x-is-trigger": False,
            "x-display-name": "Get Site Audit Campaign Info",
        },
        title="Get Site Audit Campaign Info",
    )
    project_id: str = Field(..., title="Project ID")


class SemrushSAGetSnapshotDetailsConfig(BaseModel):
    """Get detailed snapshot overview (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_audit_snapshot_details"] = Field(
        default="get_audit_snapshot_details",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Site Audit",
            "x-is-trigger": False,
            "x-display-name": "Get Audit Snapshot Details",
        },
        title="Get Audit Snapshot Details",
    )
    project_id: str = Field(..., title="Project ID")
    snapshot_id: str = Field(..., title="Snapshot ID")


class SemrushSAGetIssueDetailsConfig(BaseModel):
    """Get pages affected by a specific issue (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_pages_affected_by_issue"] = Field(
        default="get_pages_affected_by_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Site Audit",
            "x-is-trigger": False,
            "x-display-name": "Get Pages Affected by Issue",
        },
        title="Get Pages Affected by Issue",
    )
    project_id: str = Field(..., title="Project ID")
    snapshot_id: str = Field(..., title="Snapshot ID")
    issue_id: str = Field(..., title="Issue ID")
    display_limit: Optional[int] = Field(default=10, title="Limit")


class SemrushSAGetIssueMetadataConfig(BaseModel):
    """Get explanation of an issue type (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_issue_type_explanation"] = Field(
        default="get_issue_type_explanation",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Site Audit",
            "x-is-trigger": False,
            "x-display-name": "Get Issue Type Explanation",
        },
        title="Get Issue Type Explanation",
    )
    issue_id: str = Field(..., title="Issue ID")


class SemrushSASearchPageConfig(BaseModel):
    """Search for a page by URL (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_audit_page_by_url"] = Field(
        default="search_audit_page_by_url",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Site Audit",
            "x-is-trigger": False,
            "x-display-name": "Search Audit Page by Url",
        },
        title="Search Audit Page by Url",
    )
    project_id: str = Field(..., title="Project ID")
    url: str = Field(..., title="Page URL")


class SemrushSAGetPageInfoConfig(BaseModel):
    """Get page details and issues (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_audited_page_details"] = Field(
        default="get_audited_page_details",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Site Audit",
            "x-is-trigger": False,
            "x-display-name": "Get Audited Page Details",
        },
        title="Get Audited Page Details",
    )
    project_id: str = Field(..., title="Project ID")
    page_id: str = Field(..., title="Page ID")


class SemrushSAGetHistoryConfig(BaseModel):
    """Get audit history across snapshots (API v3)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_site_audit_history"] = Field(
        default="get_site_audit_history",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Site Audit",
            "x-is-trigger": False,
            "x-display-name": "Get Site Audit History",
        },
        title="Get Site Audit History",
    )
    project_id: str = Field(..., title="Project ID")
    start_date: str = Field(..., title="Start Date (YYYY-MM-DD)")
    end_date: str = Field(..., title="End Date (YYYY-MM-DD)")


# ============================================================================
# Union Type - Combines All 101 API v3 Operations
# ============================================================================

SemrushConfig = Annotated[
    Union[
        # API v3 - Analytics API: Domain Reports (12)
        SemrushDomainOrganicConfig,
        SemrushDomainAdwordsConfig,
        SemrushDomainAdwordsUniqueConfig,
        SemrushDomainOrganicOrganicConfig,
        SemrushDomainAdwordsAdwordsConfig,
        SemrushDomainAdwordsHistoricalConfig,
        SemrushDomainDomainsConfig,
        SemrushDomainShoppingConfig,
        SemrushDomainShoppingUniqueConfig,
        SemrushDomainShoppingShoppingConfig,
        SemrushDomainOrganicUniqueConfig,
        SemrushDomainOrganicSubdomainsConfig,
        # API v3 - Analytics API: Overview Reports (5)
        SemrushDomainRanksConfig,
        SemrushDomainRankConfig,
        SemrushDomainRankHistoryConfig,
        SemrushRankDifferenceConfig,
        SemrushRankConfig,
        # API v3 - Analytics API: Subdomain Reports (7)
        SemrushSubdomainRankConfig,
        SemrushSubdomainRanksConfig,
        SemrushSubdomainRankHistoryConfig,
        SemrushSubdomainOrganicConfig,
        SemrushSubdomainAdwordsConfig,
        SemrushSubdomainOrganicUniqueConfig,
        SemrushSubdomainAdwordsUniqueConfig,
        # API v3 - Analytics API: Subfolder Reports (7)
        SemrushSubfolderRankConfig,
        SemrushSubfolderRanksConfig,
        SemrushSubfolderRankHistoryConfig,
        SemrushSubfolderOrganicConfig,
        SemrushSubfolderAdwordsConfig,
        SemrushSubfolderOrganicUniqueConfig,
        SemrushSubfolderAdwordsUniqueConfig,
        # API v3 - Analytics API: URL Reports (5)
        SemrushUrlRankConfig,
        SemrushUrlRanksConfig,
        SemrushUrlRankHistoryConfig,
        SemrushUrlOrganicConfig,
        SemrushUrlAdwordsConfig,
        # API v3 - Analytics API: Keyword Reports (10)
        SemrushPhraseAllConfig,
        SemrushPhraseThisConfig,
        SemrushPhraseTheseConfig,
        SemrushPhraseOrganicConfig,
        SemrushPhraseAdwordsConfig,
        SemrushPhraseRelatedConfig,
        SemrushPhraseAdwordsHistoricalConfig,
        SemrushPhraseFullsearchConfig,
        SemrushPhraseQuestionsConfig,
        SemrushPhraseKdiConfig,
        # API v3 - Analytics API: Backlinks Reports (15)
        SemrushBacklinksOverviewConfig,
        SemrushBacklinksConfig,
        SemrushBacklinksRefdomainsConfig,
        SemrushBacklinksRefipsConfig,
        SemrushBacklinksTldConfig,
        SemrushBacklinksGeoConfig,
        SemrushBacklinksAnchorsConfig,
        SemrushBacklinksPagesConfig,
        SemrushBacklinksCompetitorsConfig,
        SemrushBacklinksMatrixConfig,
        SemrushBacklinksComparisonConfig,
        SemrushBacklinksAscoreProfileConfig,
        SemrushBacklinksCategoriesProfileConfig,
        SemrushBacklinksCategoriesConfig,
        SemrushBacklinksHistoricalConfig,
        # API v3 - Trends API (13)
        SemrushTrafficSummaryConfig,
        SemrushTrafficDailyConfig,
        SemrushTrafficWeeklyConfig,
        SemrushPurchaseConversionConfig,
        SemrushIndustryCategoriesConfig,
        SemrushTrafficSourcesConfig,
        SemrushTrafficDestinationsConfig,
        SemrushGeoDistributionConfig,
        SemrushSubdomainsTrafficConfig,
        SemrushTopPagesConfig,
        SemrushTrafficRankConfig,
        SemrushAudienceInsightsConfig,
        SemrushSubfoldersTrafficConfig,
        # API v3 - Projects API: Position Tracking (16)
        SemrushPTCampaignListConfig,
        SemrushPTCreateCampaignConfig,
        SemrushPTAddKeywordsConfig,
        SemrushPTRemoveKeywordsConfig,
        SemrushPTAddTagsConfig,
        SemrushPTRemoveTagsConfig,
        SemrushPTAddCompetitorsConfig,
        SemrushPTRemoveCompetitorsConfig,
        SemrushPTLocationSearchConfig,
        SemrushPTCampaignDatesConfig,
        SemrushPTOrganicOverviewConfig,
        SemrushPTAdwordsOverviewConfig,
        SemrushPTOrganicPositionsConfig,
        SemrushPTAdwordsPositionsConfig,
        SemrushPTEnableNotificationsConfig,
        SemrushPTDisableNotificationsConfig,
        # API v3 - Projects API: Site Audit (11)
        SemrushSAEnableConfig,
        SemrushSAEditCampaignConfig,
        SemrushSAGetSnapshotsConfig,
        SemrushSALaunchAuditConfig,
        SemrushSAGetCampaignInfoConfig,
        SemrushSAGetSnapshotDetailsConfig,
        SemrushSAGetIssueDetailsConfig,
        SemrushSAGetIssueMetadataConfig,
        SemrushSASearchPageConfig,
        SemrushSAGetPageInfoConfig,
        SemrushSAGetHistoryConfig,
    ],
    Discriminator("operation"),
]


# ============================================================================
# Full Node Config
# ============================================================================


class SemrushNodeFullConfig(NodeConfig[SemrushConfig, SemrushCredential]):
    """Complete Semrush node configuration with 92 operations across v3 and v4 APIs"""

    pass


# ============================================================================
# Semrush Node Implementation
# ============================================================================


class SemrushNode(WorkflowNode):
    """Semrush SEO & Marketing Analytics node with comprehensive API coverage"""

    edit_examples = [
        "Find organic keywords for competitor site techcrunch.com in US",
        "Get paid search keywords and ad copies for amazon.com",
        "Compare SEO metrics across 3 e-commerce competitors",
        "Research backlinks for domain and top referral domains",
        "Find keyword opportunities with low competition high volume",
        "Get traffic trends for example.com over last 6 months",
        "Analyze market share vs top 5 competitors in tech vertical",
    ]

    # API v3 base URLs
    V3_ANALYTICS_BASE = "https://api.semrush.com"
    V3_PROJECTS_BASE = "https://api.semrush.com"
    V3_TRENDS_BASE = "https://api.semrush.com/analytics/ta/api/v3"

    @classmethod
    def get_config_model(cls) -> Optional[type]:
        return SemrushNodeFullConfig

    # Flat dispatch map: operation name -> handler category.
    # Built once at class load so renamed (verb-phrase) op names route correctly
    # without relying on prefix matching.
    _DOMAIN_OPS = frozenset({
        "get_domain_organic_keywords",
        "get_domain_paid_keywords",
        "get_domain_unique_ad_copies",
        "get_domain_organic_competitors",
        "get_domain_paid_competitors",
        "get_domain_paid_keywords_historical",
        "compare_domains_batch",
        "get_domain_product_listing_keywords",
        "get_domain_unique_product_listing_ads",
        "get_domain_product_listing_competitors",
        "get_domain_top_organic_pages",
        "get_domain_subdomains_organic_ranking",
        "get_domain_overview_all_databases",
        "get_domain_overview_single_database",
        "get_domain_rank_history",
        "get_winners_and_losers_report",
        "get_semrush_rank_report",
        "get_subdomain_overview_single_database",
        "get_subdomain_overview_all_databases",
        "get_subdomain_rank_history",
        "get_subdomain_organic_keywords",
        "get_subdomain_paid_keywords",
        "get_subdomain_top_organic_pages",
        "get_subdomain_unique_ad_copies",
        "get_subfolder_overview_single_database",
        "get_subfolder_overview_all_databases",
        "get_subfolder_rank_history",
        "get_subfolder_organic_keywords",
        "get_subfolder_paid_keywords",
        "get_subfolder_top_organic_pages",
        "get_subfolder_unique_ad_copies",
        "get_url_overview_single_database",
        "get_url_overview_all_databases",
        "get_url_rank_history",
        "get_url_organic_keywords",
        "get_url_paid_keywords",
    })
    _KEYWORD_OPS = frozenset({
        "get_keyword_overview_all_databases",
        "get_keyword_overview_single_database",
        "get_batch_keyword_overview",
        "get_keyword_organic_search_results",
        "get_keyword_paid_search_results",
        "get_related_keywords",
        "get_keyword_ads_historical_data",
        "get_broad_match_keywords",
        "get_question_keywords",
        "get_keyword_difficulty",
    })
    _BACKLINKS_OPS = frozenset({
        "get_backlinks_overview",
        "get_backlinks_list",
        "get_referring_domains",
        "get_referring_ip_addresses",
        "get_backlinks_by_tld",
        "get_backlinks_by_country",
        "get_backlink_anchor_distribution",
        "get_pages_with_backlinks",
        "get_backlink_competitors",
        "compare_backlinks_between_domains",
        "compare_backlink_profiles_batch",
        "get_authority_score_distribution",
        "get_referring_domain_categories",
        "get_target_domain_categories",
        "get_backlinks_historical_data",
    })
    _TRENDS_OPS = frozenset({
        "get_traffic_summary_for_domains",
        "get_daily_traffic_breakdown",
        "get_weekly_traffic_breakdown",
        "get_purchase_conversion_rates",
        "get_domains_by_industry_category",
        "get_traffic_sources_breakdown",
        "get_traffic_destinations",
        "get_geographic_traffic_distribution",
        "get_subdomain_traffic",
        "get_top_pages_by_traffic",
        "get_traffic_rank_for_domains",
        "get_audience_demographics",
        "get_subfolder_traffic",
    })
    _POSITION_TRACKING_OPS = frozenset({
        "list_position_tracking_campaigns",
        "create_position_tracking_campaign",
        "add_keywords_to_tracking_campaign",
        "remove_keywords_from_tracking_campaign",
        "add_tags_to_tracked_keywords",
        "remove_tags_from_tracked_keywords",
        "add_competitors_to_tracking_campaign",
        "remove_competitors_from_tracking_campaign",
        "search_tracking_locations",
        "get_tracking_campaign_harvest_dates",
        "get_organic_tracking_overview",
        "get_paid_search_tracking_overview",
        "get_organic_keyword_positions",
        "get_paid_search_keyword_positions",
        "enable_campaign_email_notifications",
        "disable_campaign_email_notifications",
    })
    _SITE_AUDIT_OPS = frozenset({
        "enable_site_audit_for_project",
        "update_site_audit_campaign",
        "list_audit_snapshots",
        "launch_site_audit",
        "get_site_audit_campaign_info",
        "get_audit_snapshot_details",
        "get_pages_affected_by_issue",
        "get_issue_type_explanation",
        "search_audit_page_by_url",
        "get_audited_page_details",
        "get_site_audit_history",
    })

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the Semrush operation"""
        config = self.config
        if not config or not isinstance(config, SemrushNodeFullConfig):
            raise ValueError("Configuration required")

        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials required. Connect your Semrush account or add API key."
            )

        operation = config.config
        action = operation.operation

        # Route to appropriate handler based on operation name
        if action in self._DOMAIN_OPS:
            return await self._execute_domain_report(operation, credentials)
        elif action in self._KEYWORD_OPS:
            return await self._execute_keyword_report(operation, credentials)
        elif action in self._BACKLINKS_OPS:
            return await self._execute_backlinks_report(operation, credentials)
        elif action in self._TRENDS_OPS:
            return await self._execute_trends_report(operation, credentials)
        elif action in self._POSITION_TRACKING_OPS:
            return await self._execute_position_tracking(operation, credentials)
        elif action in self._SITE_AUDIT_OPS:
            return await self._execute_site_audit(operation, credentials)
        else:
            raise ValueError(f"Unknown operation: {action}")

    # ========================================================================
    # API v3 - Analytics API Handlers
    # ========================================================================

    async def _execute_domain_report(self, operation, credentials) -> Dict[str, Any]:
        """Execute Analytics API domain/overview/subdomain/subfolder/URL report"""
        api_key = self._get_api_key(credentials)
        action = operation.operation

        # Build parameters
        params = {
            "type": action,
            "key": api_key,
            "display_limit": getattr(operation, "display_limit", 10),
            "export_columns": getattr(operation, "export_columns", None),
        }

        # Add operation-specific parameters
        if hasattr(operation, "domain"):
            params["domain"] = operation.domain
        if hasattr(operation, "domains"):
            params["domains"] = operation.domains
        if hasattr(operation, "url"):
            params["url"] = operation.url
        if hasattr(operation, "database"):
            params["database"] = operation.database
        if hasattr(operation, "display_filter"):
            params["display_filter"] = operation.display_filter
        if hasattr(operation, "display_daily"):
            params["display_daily"] = "1" if operation.display_daily else "0"

        # Remove None values
        params = {k: v for k, v in params.items() if v is not None}

        async with httpx.AsyncClient() as client:
            response = await client.get(self.V3_ANALYTICS_BASE, params=params)
            response.raise_for_status()

            # Parse CSV response
            csv_data = response.text
            return {
                "success": True,
                "action": action,
                "data": csv_data,
                "format": "csv",
                "message": f"Retrieved {action} data",
            }

    async def _execute_keyword_report(self, operation, credentials) -> Dict[str, Any]:
        """Execute Analytics API keyword report"""
        api_key = self._get_api_key(credentials)
        action = operation.operation

        params = {
            "type": action,
            "key": api_key,
            "export_columns": getattr(operation, "export_columns", None),
        }

        if hasattr(operation, "phrase"):
            params["phrase"] = operation.phrase
        if hasattr(operation, "phrases"):
            params["phrases"] = operation.phrases
        if hasattr(operation, "database"):
            params["database"] = operation.database
        if hasattr(operation, "display_limit"):
            params["display_limit"] = operation.display_limit

        params = {k: v for k, v in params.items() if v is not None}

        async with httpx.AsyncClient() as client:
            response = await client.get(self.V3_ANALYTICS_BASE, params=params)
            response.raise_for_status()

            return {
                "success": True,
                "action": action,
                "data": response.text,
                "format": "csv",
            }

    async def _execute_backlinks_report(self, operation, credentials) -> Dict[str, Any]:
        """Execute Analytics API backlinks report"""
        api_key = self._get_api_key(credentials)
        action = operation.operation

        params = {
            "type": action,
            "key": api_key,
            "target_type": getattr(operation, "target_type", "root_domain"),
            "export_columns": getattr(operation, "export_columns", None),
            "display_limit": getattr(operation, "display_limit", None),
        }

        if hasattr(operation, "target"):
            params["target"] = operation.target
        if hasattr(operation, "targets"):
            params["targets"] = operation.targets

        params = {k: v for k, v in params.items() if v is not None}

        async with httpx.AsyncClient() as client:
            response = await client.get(self.V3_ANALYTICS_BASE, params=params)
            response.raise_for_status()

            return {
                "success": True,
                "action": action,
                "data": response.text,
                "format": "csv",
            }

    # ========================================================================
    # API v3 - Trends API Handler
    # ========================================================================

    async def _execute_trends_report(self, operation, credentials) -> Dict[str, Any]:
        """Execute Trends API report"""
        api_key = self._get_api_key(credentials)
        action = operation.operation

        # Map action to endpoint
        endpoint_map = {
            "get_traffic_summary_for_domains": "summary",
            "get_daily_traffic_breakdown": "summary_by_day",
            "get_weekly_traffic_breakdown": "summary_by_week",
            "get_purchase_conversion_rates": "purchase_conversion",
            "get_domains_by_industry_category": "categories",
            "get_traffic_sources_breakdown": "sources",
            "get_traffic_destinations": "destinations",
            "get_geographic_traffic_distribution": "geo",
            "get_subdomain_traffic": "subdomains",
            "get_top_pages_by_traffic": "toppages",
            "get_traffic_rank_for_domains": "rank",
            "get_audience_demographics": "audience",
            "get_subfolder_traffic": "subfolders",
        }

        endpoint = endpoint_map.get(action, action)
        url = f"{self.V3_TRENDS_BASE}/{endpoint}"

        params = {"key": api_key}

        if hasattr(operation, "target"):
            params["target"] = operation.target
        if hasattr(operation, "targets"):
            params["targets"] = operation.targets
        if hasattr(operation, "country"):
            params["country"] = operation.country
        if hasattr(operation, "device_type"):
            params["device_type"] = operation.device_type
        if hasattr(operation, "display_limit"):
            params["display_limit"] = operation.display_limit
        if hasattr(operation, "category"):
            params["category"] = operation.category

        params = {k: v for k, v in params.items() if v is not None}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()

            return {
                "success": True,
                "action": action,
                "data": response.text,
                "format": "csv",
            }

    # ========================================================================
    # API v3 - Projects API Handlers
    # ========================================================================

    async def _execute_position_tracking(
        self, operation, credentials
    ) -> Dict[str, Any]:
        """Execute Position Tracking API operation"""
        api_key = self._get_api_key(credentials)
        action = operation.operation

        # Map actions to endpoints
        if action == "list_position_tracking_campaigns":
            url = f"{self.V3_PROJECTS_BASE}/management/v1/projects/{operation.project_id}/tracking/campaigns"
            method = "GET"
            params = {"key": api_key}
            json_data = None
        elif action == "create_position_tracking_campaign":
            url = f"{self.V3_PROJECTS_BASE}/management/v1/projects/{operation.project_id}/tracking/enable"
            method = "POST"
            params = {"key": api_key}
            json_data = {
                "domain": operation.domain,
                "location_id": operation.location_id,
                "device": operation.device,
                "keywords": operation.keywords.split(","),
            }
        elif action == "add_keywords_to_tracking_campaign":
            url = f"{self.V3_PROJECTS_BASE}/management/v1/projects/{operation.campaign_id}/keywords"
            method = "PUT"
            params = {"key": api_key}
            json_data = {"keywords": operation.keywords.split(",")}
        elif action == "remove_keywords_from_tracking_campaign":
            url = f"{self.V3_PROJECTS_BASE}/management/v1/projects/{operation.campaign_id}/keywords"
            method = "DELETE"
            params = {"key": api_key}
            json_data = {"keyword_ids": operation.keyword_ids.split(",")}
        elif action == "search_tracking_locations":
            url = f"{self.V3_PROJECTS_BASE}/position-tracking/management/v1/info/locations"
            method = "GET"
            params = {"key": api_key, "query": operation.query}
            json_data = None
        elif action == "get_tracking_campaign_harvest_dates":
            url = f"{self.V3_PROJECTS_BASE}/management/v1/projects/{operation.campaign_id}/tracking/dates"
            method = "GET"
            params = {"key": api_key}
            json_data = None
        elif action == "add_tags_to_tracked_keywords":
            url = f"{self.V3_PROJECTS_BASE}/management/v1/projects/{operation.campaign_id}/tracking/tags"
            method = "PUT"
            params = {"key": api_key}
            json_data = {
                "keyword_ids": operation.keyword_ids.split(","),
                "tags": operation.tags.split(","),
            }
        elif action == "remove_tags_from_tracked_keywords":
            url = f"{self.V3_PROJECTS_BASE}/management/v1/projects/{operation.campaign_id}/tracking/tags"
            method = "DELETE"
            params = {"key": api_key}
            json_data = {
                "keyword_ids": operation.keyword_ids.split(","),
                "tags": operation.tags.split(","),
            }
        elif action == "add_competitors_to_tracking_campaign":
            url = f"{self.V3_PROJECTS_BASE}/management/v1/projects/{operation.campaign_id}/tracking/competitors"
            method = "PUT"
            params = {"key": api_key}
            json_data = {"competitors": operation.competitors.split(",")}
        elif action == "remove_competitors_from_tracking_campaign":
            url = f"{self.V3_PROJECTS_BASE}/management/v1/projects/{operation.campaign_id}/tracking/competitors"
            method = "DELETE"
            params = {"key": api_key}
            json_data = {"competitors": operation.competitors.split(",")}
        elif action in {
            "get_organic_tracking_overview",
            "get_paid_search_tracking_overview",
            "get_organic_keyword_positions",
            "get_paid_search_keyword_positions",
        }:
            # Report endpoints
            report_type_map = {
                "get_organic_tracking_overview": "tracking_overview_organic",
                "get_paid_search_tracking_overview": "tracking_overview_adwords",
                "get_organic_keyword_positions": "tracking_position_organic",
                "get_paid_search_keyword_positions": "tracking_position_adwords",
            }
            url = f"{self.V3_PROJECTS_BASE}/reports/v1/projects/{operation.campaign_id}/tracking/"
            method = "GET"
            params = {
                "key": api_key,
                "type": report_type_map.get(action),
                "display_date": getattr(operation, "display_date", None),
                "display_limit": getattr(operation, "display_limit", None),
            }
            params = {k: v for k, v in params.items() if v is not None}
            json_data = None
        else:
            # Other management endpoints (enable/disable email notifications, etc.)
            url = f"{self.V3_PROJECTS_BASE}/management/v1/projects/{operation.campaign_id}/tracking/"
            method = "PUT" if "add" in action or "enable" in action else "DELETE"
            params = {"key": api_key}
            json_data = {}

        async with httpx.AsyncClient() as client:
            if method == "GET":
                response = await client.get(url, params=params)
            elif method == "POST":
                response = await client.post(url, params=params, json=json_data)
            elif method == "PUT":
                response = await client.put(url, params=params, json=json_data)
            elif method == "DELETE":
                response = await client.delete(url, params=params, json=json_data)

            response.raise_for_status()

            try:
                data = await response.json()
            except:
                data = response.text

            return {"success": True, "action": action, "data": data}

    async def _execute_site_audit(self, operation, credentials) -> Dict[str, Any]:
        """Execute Site Audit API operation"""
        api_key = self._get_api_key(credentials)
        action = operation.operation

        # Map actions to endpoints
        if action == "enable_site_audit_for_project":
            url = f"{self.V3_PROJECTS_BASE}/management/v1/projects/{operation.project_id}/siteaudit/enable"
            method = "POST"
            json_data = {
                "domain": operation.domain,
                "crawl_subdomains": getattr(operation, "crawl_subdomains", False),
                "max_pages": getattr(operation, "max_pages", 100),
            }
        elif action == "update_site_audit_campaign":
            url = f"{self.V3_PROJECTS_BASE}/management/v1/projects/{operation.project_id}/siteaudit/save"
            method = "POST"
            json_data = {
                k: v
                for k, v in {
                    "max_pages": getattr(operation, "max_pages", None),
                    "crawl_subdomains": getattr(operation, "crawl_subdomains", None),
                }.items()
                if v is not None
            }
        elif action == "launch_site_audit":
            url = f"{self.V3_PROJECTS_BASE}/reports/v1/projects/{operation.project_id}/siteaudit/launch"
            method = "POST"
            json_data = {}
        elif action == "list_audit_snapshots":
            url = f"{self.V3_PROJECTS_BASE}/reports/v1/projects/{operation.project_id}/siteaudit/snapshots"
            method = "GET"
            json_data = None
        elif action == "get_site_audit_campaign_info":
            url = f"{self.V3_PROJECTS_BASE}/reports/v1/projects/{operation.project_id}/siteaudit/info"
            method = "GET"
            json_data = None
        elif action == "get_audit_snapshot_details":
            url = f"{self.V3_PROJECTS_BASE}/reports/v1/projects/{operation.project_id}/siteaudit/snapshot"
            method = "GET"
            json_data = None
        elif action == "get_pages_affected_by_issue":
            url = f"{self.V3_PROJECTS_BASE}/reports/v1/projects/{operation.project_id}/siteaudit/snapshot/{operation.snapshot_id}/issue/{operation.issue_id}"
            method = "GET"
            json_data = None
        elif action == "get_issue_type_explanation":
            url = f"{self.V3_PROJECTS_BASE}/reports/v1/projects/meta/issues"
            method = "GET"
            json_data = None
        elif action == "search_audit_page_by_url":
            url = f"{self.V3_PROJECTS_BASE}/reports/v1/projects/{operation.project_id}/siteaudit/page/list"
            method = "GET"
            json_data = None
        elif action == "get_audited_page_details":
            url = f"{self.V3_PROJECTS_BASE}/reports/v1/projects/{operation.project_id}/siteaudit/page/{operation.page_id}"
            method = "GET"
            json_data = None
        elif action == "get_site_audit_history":
            url = f"{self.V3_PROJECTS_BASE}/reports/v1/projects/{operation.project_id}/siteaudit/history"
            method = "GET"
            json_data = None

        params = {"key": api_key}

        async with httpx.AsyncClient() as client:
            if method == "GET":
                response = await client.get(url, params=params)
            elif method == "POST":
                response = await client.post(url, params=params, json=json_data)

            response.raise_for_status()

            try:
                data = await response.json()
            except:
                data = response.text

            return {"success": True, "action": action, "data": data}

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def _get_api_key(self, credentials) -> str:
        """Extract API key from credentials"""
        if isinstance(credentials, SemrushAPIKeyCredential):
            return credentials.api_key
        else:
            raise ValueError("API v3 operations require API Key credentials")
