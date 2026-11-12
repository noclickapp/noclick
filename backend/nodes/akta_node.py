"""Akta research API v1: fixed operations from the published OpenAPI contract."""
from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.akta.pro/api"


class AktaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Akta API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://playground.akta.pro/",
        "x-credential-instructions": "Copy your API key from the Akta playground and paste it here. Akta research endpoints prove key acceptance, not account identity. Some data sections require a Subscription or Enterprise plan."})
    credential_type: Literal["akta_api_key"] = Field("akta_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("products", "filters", "sections", mode="before", check_fields=False)
    @classmethod
    def json_input(cls, value, info):
        # Text config fields and upstream references can supply JSON text.
        # Enrichment sections are comma-separated text; list sections are an array.
        if isinstance(value, str) and cls.model_fields[info.field_name].annotation != (str | None):
            try:
                return json.loads(value)
            except ValueError:
                raise ValueError("Enter a valid JSON array or object") from None
        return value

    @model_validator(mode="after")
    def semantics(self):
        if getattr(self, "company", None) and getattr(self, "primary_company", None):
            raise ValueError("Choose company or primary_company")
        if getattr(self, "query", None) and getattr(self, "filters", None) is not None:
            raise ValueError("Choose query or filters")
        start, end = getattr(self, "start_date", None), getattr(self, "end_date", None)
        if start and end and start > end:
            raise ValueError("End date must be on or after start date")
        return self



class AktaGetNewsConfig(_Input):
    """News."""
    operation: Literal["get_news"] = Field("get_news", json_schema_extra={"ui:hidden": True})
    company: str | None = Field(None, description="Website (e.g. 'https://canva.com') or company UUID returned by the Company Search API.", min_length=1)
    primary_company: str | None = Field(None, description='Filter to return only articles where the specified company is the primary company featured. Cannot be used with the `company` parameter.', min_length=1)
    industry: str | None = Field(None, description='Comma separated list of industry codes to filter articles by. Use industry search endpoint to fetch the list of industry codes for a given industry topic.', min_length=1)
    query: str | None = Field(None, description='Topic name to search articles. Allows open-ended topic name. Eg. Crude oil price developments', min_length=1)
    title: str | None = Field(None, description='Searches articles based on the title entered.', min_length=1)
    start_date: date | None = Field(None, description='Start of the date range, formatted as YYYY-MM-DD. Non-enterprise plans are limited to a 6-month lookback.')
    end_date: date | None = Field(None, description='End of the date range, formatted as YYYY-MM-DD. Default = today.')
    limit: int = Field(10, description='Maximum number of news articles to return. Default = 10, Max = 100.', ge=0, le=100)
    offset: int = Field(0, description='Number of results to skip before returning records. Use with limit for pagination.', ge=0)
    group_articles: bool | None = Field(None, description='Accepts boolean. True will group similar articles from the same event.')
    news_score_list: Literal['High', 'Medium', 'Low', 'all'] | None = Field(None, description='Filter by news score tier. Accepted values: High, Medium, Low, all. Default = all', min_length=1)
    countries: str | None = Field(None, description='Filters articles based on the country of the event. Comma separated list of ISO country codes.', min_length=1)
    blacklisted: str | None = Field(None, description='Comma separated list of publisher domains to exclude.', min_length=1)
    type_list: str | None = Field(None, description='Filter by news type. Download full list from https://playground.akta.pro/news-tags.csv. Default = all.', min_length=1)
    sentiment_list: str | None = Field(None, description='Comma-separated list of sentiments to filter by. Accepted values: positive, negative, neutral, all. Default = all. Example: sentiment_list=positive,negative', min_length=1)
    entity_person_list: str | None = Field(None, description='Comma separated list of people names.', min_length=1)
    entity_location_list: str | None = Field(None, description='Comma separated list of locations.', min_length=1)
    entity_product_list: str | None = Field(None, description='Comma separated list of product names.', min_length=1)
    entity_event_list: str | None = Field(None, description='Comma separated list of event names.', min_length=1)
    naics_code_list: str | None = Field(None, description='Comma separated list of NAICS codes.', min_length=1)
    sic_code_list: str | None = Field(None, description='Comma separated list of SIC codes.', min_length=1)
    iptc_code_list: str | None = Field(None, description='Comma separated list of IPTC codes.', min_length=1)
    iab_code_list: str | None = Field(None, description='Comma separated list of IAB codes.', min_length=1)


class AktaSearchCompaniesConfig(_Input):
    """Company Search."""
    operation: Literal["search_companies"] = Field("search_companies", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., description='A company name, website. The backend automatically resolves the input type. Examples: https://canva.com, canva', min_length=1)


class AktaEnrichCompanyConfig(_Input):
    """Company Enrichment."""
    operation: Literal["enrich_company"] = Field("enrich_company", json_schema_extra={"ui:hidden": True})
    company: str = Field(..., description="Company website (e.g. 'https://canva.com') or a company UUID (e.g. '00031n-tesla'). The UUID can be obtained from the Company Search API.", min_length=1)
    sections: str | None = Field(None, description='Comma-separated list of sections to return. Copy-paste example: `firmographic,business_model,company_assessment,trust_signal,company_hierarchy,digital_presence,financial_estimate,location,management_profile,product_offering,strategic_signal,customer_profile,industry,technology,funding_detail,mna_and_investment`. Note: `funding_detail` and `mna_and_investment` are available on the subscription and Enterprise tier only.', min_length=1)


class AktaGetProductReviewsConfig(_Input):
    """Product Reviews."""
    operation: Literal["get_product_reviews"] = Field("get_product_reviews", json_schema_extra={"ui:hidden": True})
    company: str = Field(..., description="Company website (e.g. 'canva.com') or a company UUID. The UUID can be obtained from the Company Search API.", min_length=1)
    products: list[str] | None = Field(None, description='List of product_id values to fetch reviews for. Pass the parameter multiple times to request more than one product. If omitted, the response returns the product list only.')
    limit: int = Field(0, description='Maximum number of reviews to return per product. Only applies when products is provided.', ge=0, le=50)
    offset: int = Field(0, description='Number of reviews to skip before returning records. Use with limit for pagination.', ge=0)


class AktaGetEmployeeReviewsConfig(_Input):
    """Employee Reviews."""
    operation: Literal["get_employee_reviews"] = Field("get_employee_reviews", json_schema_extra={"ui:hidden": True})
    company: str = Field(..., description="Company website (e.g. 'canva.com') or a company UUID. The UUID can be obtained from the Company Search API.", min_length=1)
    limit: int = Field(10, description='Maximum number of reviews to return.', ge=0, le=100)
    offset: int = Field(0, description='Number of reviews to skip before returning records. Use with limit for pagination.', ge=0)


class AktaSearchIndustriesConfig(_Input):
    """Industry Search."""
    operation: Literal["search_industries"] = Field("search_industries", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., description="Free-text industry name or topic to search for. Example: 'warehouse automation'", min_length=1)
    level: str | None = Field(None, description='Restrict results to one or more levels of the industry taxonomy hierarchy. Accepts a single level or a comma-separated list of multiple levels. Available values: l1, l2, l3, l4, all. Default is l4.', min_length=1)


class AktaGetHeadcountTrendsConfig(_Input):
    """Headcount Trends."""
    operation: Literal["get_headcount_trends"] = Field("get_headcount_trends", json_schema_extra={"ui:hidden": True})
    company: str = Field(..., description="Company website (e.g. 'canva.com') or a company UUID. The UUID can be obtained from the Company Search API.", min_length=1)


class AktaGetJobPostsConfig(_Input):
    """Job Posts."""
    operation: Literal["get_job_posts"] = Field("get_job_posts", json_schema_extra={"ui:hidden": True})
    company: str = Field(..., description="Company website (e.g. 'canva.com') or a company UUID. The UUID can be obtained from the Company Search API.", min_length=1)
    limit: int = Field(10, description='Maximum number of job listings to return.', ge=0)
    offset: int = Field(0, description='Number of listings to skip before returning records.', ge=0)


class AktaGetSocialPostsConfig(_Input):
    """Social Posts."""
    operation: Literal["get_social_posts"] = Field("get_social_posts", json_schema_extra={"ui:hidden": True})
    company: str = Field(..., description="Company website (e.g. 'canva.com') or a company UUID. The UUID can be obtained from the Company Search API.", min_length=1)
    limit: int = Field(10, description='Maximum number of posts to return.', ge=0)
    offset: int = Field(0, description='Number of posts to skip before returning records.', ge=0)


class AktaGetWebsiteTrafficConfig(_Input):
    """Website Traffic."""
    operation: Literal["get_website_traffic"] = Field("get_website_traffic", json_schema_extra={"ui:hidden": True})
    company: str = Field(..., description="Company website (e.g. 'canva.com') or a company UUID. The UUID can be obtained from the Company Search API.", min_length=1)


class AktaCreateCompanyAdditionRequestConfig(_Input):
    """Company Addition."""
    operation: Literal["create_company_addition_request"] = Field("create_company_addition_request", json_schema_extra={"ui:hidden": True})
    company_name: str = Field(..., description='Name of the company to add. Example: solios', min_length=1)
    website: str = Field(..., description='Primary website URL of the company. Used to disambiguate and resolve the company. Example: https://www.soleosenergy.com/', min_length=1)


class AktaGetRequestStatusConfig(_Input):
    """Request Status."""
    operation: Literal["get_request_status"] = Field("get_request_status", json_schema_extra={"ui:hidden": True})
    request_id: str = Field(..., pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$', description='The unique identifier of the request to check, returned when the original request was submitted. Example: 2db01b38-5c81-4b3f-b76d-8b36aeed603b', min_length=1)


class AktaGenerateCompanyListConfig(_Input):
    """Generate Company List."""
    operation: Literal["generate_company_list"] = Field("generate_company_list", json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, description="Natural language search query (e.g. 'SaaS companies in the US with Series A funding'). Cannot be used with filters.", min_length=1)
    filters: dict | None = Field(None, description='Structured filter conditions. Use the Filter Builder API to generate valid filters. Cannot be used with query. See filter options at /api-reference/listgen-api.')
    sections: list[str] | None = Field(None, description='Data enrichment sections to include. Values: firmographic, business_model, company_assessment, trust_signal, company_hierarchy, digital_presence, financial_estimate, location, management_profile, product_offering, strategic_signal, customer_profile, industry, technology, funding_detail (Subscription, Enterprise), mna_and_investment (Subscription, Enterprise)')
    sort_by: Literal['relevance', 'revenue_estimate', 'valuation_estimate', 'employee_range', 'total_funding', 'founded_year'] | None = Field(None, description='Field to sort results by. Default: relevance', min_length=1)
    sort_order: Literal['asc', 'desc'] | None = Field(None, description='Sort direction. Default: desc', min_length=1)
    limit: int | None = Field(None, description='Maximum companies to return. Default: 50, Max: 500', ge=0, le=500)
    offset: int | None = Field(None, description='Number of results to skip for pagination. Default: 0', ge=0)


class AktaBuildFiltersConfig(_Input):
    """Build Filters."""
    operation: Literal["build_filters"] = Field("build_filters", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., description="Natural language description of target companies (e.g. 'series a companies in mumbai working in climate tech').", min_length=1)


# Akta's own MCP server: agents get its tools through a person's Akta sign-in.
AktaMcpCredential = mcp_credential("akta", "https://mcp.akta.pro/mcp", app="Akta")
AktaCredential = Union[AktaAPIKeyCredential, AktaMcpCredential]


AktaConfig = Annotated[Union[AktaGetNewsConfig, AktaSearchCompaniesConfig, AktaEnrichCompanyConfig, AktaGetProductReviewsConfig, AktaGetEmployeeReviewsConfig, AktaSearchIndustriesConfig, AktaGetHeadcountTrendsConfig, AktaGetJobPostsConfig, AktaGetSocialPostsConfig, AktaGetWebsiteTrafficConfig, AktaCreateCompanyAdditionRequestConfig, AktaGetRequestStatusConfig, AktaGenerateCompanyListConfig, AktaBuildFiltersConfig], Field(discriminator="operation")]


class AktaFullConfig(NodeConfig[AktaConfig, AktaCredential]):
    pass


ROUTES = {'get_news': ('GET', '/v1/news'), 'search_companies': ('GET', '/v1/company/search'), 'enrich_company': ('GET', '/v1/company/enrichment'), 'get_product_reviews': ('GET', '/v1/company/product-reviews'), 'get_employee_reviews': ('GET', '/v1/company/employee-reviews'), 'search_industries': ('GET', '/v1/industry/search'), 'get_headcount_trends': ('GET', '/v1/company/headcount-trends'), 'get_job_posts': ('GET', '/v1/company/jobs'), 'get_social_posts': ('GET', '/v1/company/posts'), 'get_website_traffic': ('GET', '/v1/company/website-traffic'), 'create_company_addition_request': ('POST', '/v1/company/addition-requests'), 'get_request_status': ('GET', '/v1/status/{request_id}'), 'generate_company_list': ('POST', '/v1/list/generate/companies/'), 'build_filters': ('POST', '/v1/list/filter-builder/')}


class AktaNode(WorkflowNode):
    integration_type = "automation-akta"
    credential_provider_labels = {"akta": "Akta Account"}
    connection_evidence = ConnectionEvidence(noun="Akta company search", operation="search_companies", operation_arguments={"query": "canva"}, proves="reachability")

    @classmethod
    def get_config_model(cls):
        return AktaFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an Akta API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "request_id" in values:
            path = path.replace("{request_id}", quote(values.pop("request_id"), safe=""))
        kwargs = {"params": values} if method == "GET" else {"json": values}
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"x-api-key": credential.api_key, "Accept": "application/json"}, **kwargs)
        except Exception:
            return {"status": "error", "error": "Akta request could not be completed; inspect write status before retrying"}
        if response.status_code == 204 and config.operation in {"get_news", "search_companies", "search_industries"}:
            return {"status": "success", "data": [], "http_status": 204}
        if response.status_code != 200:
            message = "Akta request rejected"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"].replace(credential.api_key, "[redacted]")[:2000]
            except ValueError:
                pass
            return {"status": "error", "error": message, "http_status": response.status_code}
        if len(response.content) > 20_000_000:
            return {"status": "error", "error": "Akta response exceeds the supported size"}
        try:
            body = response.json()
        except ValueError:
            return {"status": "error", "error": "Akta returned invalid JSON"}
        if not isinstance(body, dict) or body.get("error") or body.get("status") in ("error", "failed"):
            return {"status": "error", "error": "Akta returned an error response"}
        expected = list if config.operation in {"get_news", "search_companies", "search_industries", "get_job_posts", "generate_company_list"} else dict
        if not isinstance(body.get("data"), expected):
            return {"status": "error", "error": "Akta returned an unexpected data shape"}
        # Keep the provider's documented envelope and pagination/credit fields.
        # A submission response is an acknowledgement; get_request_status polls completion.
        return json.loads(json.dumps({"status": "success", **body}).replace(credential.api_key, "[redacted]"))
