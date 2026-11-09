"""Jungle Scout API v1 research queries, authenticated with a pasted API key.

The published contract contains six read-only research operations, including
three POST queries. No account identity or write API is published.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://developer.junglescout.com"
MEDIA_TYPE = "application/vnd.junglescout.v1+json"
Marketplace = Literal["us", "uk", "de", "in", "ca", "fr", "it", "es", "mx", "jp"]
ASIN = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]{10}$")]
TitleKeyword = Annotated[str, StringConstraints(min_length=1, max_length=50)]


class JunglescoutAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Jungle Scout API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.junglescout.com/",
            "x-credential-instructions": "Paste the key name and API key from your Jungle Scout API account. NoClick sends Authorization: key_name:api_key. A product query uses API credits and proves key acceptance, not account identity.",
        })
    credential_type: Literal["junglescout_api_key"] = Field("junglescout_api_key", json_schema_extra={"ui:hidden": True})
    marketplace: Marketplace = Field("us", description="Default Amazon marketplace permitted for this key; also used for the connection check.")
    key_name: str = Field(..., min_length=1, title="Key name", description="Name paired with your API key.")
    api_key: str = Field(..., min_length=1, title="API key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("key_name", "api_key", mode="before")
    @classmethod
    def header_part(cls, value):
        value = clean_secret(value, field_name="Jungle Scout key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 for c in value) or ":" in value:
            raise ValueError("Paste only the key name or key value, without a colon or header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    marketplace: Marketplace | None = Field(None, description="Amazon marketplace country code; defaults to the connected key marketplace.")


class _Page(_Input):
    page_size: int = Field(50, ge=1, le=100, description="Results in this page; maximum 100.")
    page_cursor: str | None = Field(None, description="Opaque page cursor returned by the previous request. Keep the same filters.")


class _Dates(_Input):
    start_date: date = Field(..., description="Start of period, YYYY-MM-DD.")
    end_date: date = Field(..., description="End of period, YYYY-MM-DD; before today.")

    @model_validator(mode="after")
    def period(self):
        if self.start_date >= self.end_date or self.end_date >= date.today():
            raise ValueError("Use an ordered period ending before today")
        return self


class KeywordsByAsin(_Page):
    operation: Literal["list_keywords_by_asin"] = Field("list_keywords_by_asin", json_schema_extra={"ui:hidden": True})
    sort: Literal['name', '-name', 'dominant_category', '-dominant_category', 'monthly_trend', '-monthly_trend', 'quarterly_trend', '-quarterly_trend', 'monthly_search_volume_exact', '-monthly_search_volume_exact', 'monthly_search_volume_broad', '-monthly_search_volume_broad', 'recommended_promotions', '-recommended_promotions', 'sp_brand_ad_bid', '-sp_brand_ad_bid', 'ppc_bid_broad', '-ppc_bid_broad', 'ppc_bid_exact', '-ppc_bid_exact', 'ease_of_ranking_score', '-ease_of_ranking_score', 'relevancy_score', '-relevancy_score', 'organic_product_count', '-organic_product_count'] = '-monthly_search_volume_exact'
    asins: list[ASIN] = Field(..., min_length=1, max_length=10, description='Array of up to 10 ASINs. If querying multiple ASINs, all comparison data points will be referenced to the first ASIN in the array')
    include_variants: bool | None = Field(None, description='Include (or exclude) ASIN variants when returning related keywords. Can result in many more keyword results. Default is `true`')
    min_monthly_search_volume_exact: int | None = Field(None, description='Filter results by minimum exact match monthly search volume')
    max_monthly_search_volume_exact: int | None = Field(None, description='Filter results by maximum exact match monthly search volume')
    min_monthly_search_volume_broad: int | None = Field(None, description='Filter results by minimum broad match monthly search volume')
    max_monthly_search_volume_broad: int | None = Field(None, description='Filter results by maximum broad match monthly search volume')
    min_word_count: int | None = Field(None, description='Filter results by minimum word count')
    max_word_count: int | None = Field(None, description='Filter results by maximum word count')
    min_organic_product_count: int | None = Field(None, description='Filter results by minimum organic product count')
    max_organic_product_count: int | None = Field(None, description='Filter results by maximum organic product count')


class KeywordsByKeyword(_Page):
    operation: Literal["list_keywords_by_keyword"] = Field("list_keywords_by_keyword", json_schema_extra={"ui:hidden": True})
    sort: Literal['name', '-name', 'dominant_category', '-dominant_category', 'monthly_trend', '-monthly_trend', 'quarterly_trend', '-quarterly_trend', 'monthly_search_volume_exact', '-monthly_search_volume_exact', 'monthly_search_volume_broad', '-monthly_search_volume_broad', 'recommended_promotions', '-recommended_promotions', 'sp_brand_ad_bid', '-sp_brand_ad_bid', 'ppc_bid_broad', '-ppc_bid_broad', 'ppc_bid_exact', '-ppc_bid_exact', 'ease_of_ranking_score', '-ease_of_ranking_score', 'relevancy_score', '-relevancy_score', 'organic_product_count', '-organic_product_count'] = '-monthly_search_volume_exact'
    categories: list[str] | None = Field(None)
    search_terms: list[str] = Field(..., min_length=1, description='Keyword or phrase to perform a search against')
    min_monthly_search_volume_exact: int | None = Field(None, description='Filter results by minimum exact match monthly search volume')
    max_monthly_search_volume_exact: int | None = Field(None, description='Filter results by maximum exact match monthly search volume')
    min_monthly_search_volume_broad: int | None = Field(None, description='Filter results by minimum broad match monthly search volume')
    max_monthly_search_volume_broad: int | None = Field(None, description='Filter results by maximum broad match monthly search volume')
    min_word_count: int | None = Field(None, description='Filter results by minimum word count')
    max_word_count: int | None = Field(None, description='Filter results by maximum word count')
    min_organic_product_count: int | None = Field(None, description='Filter results by minimum organic product count')
    max_organic_product_count: int | None = Field(None, description='Filter results by maximum organic product count')


class HistoricalSearchVolume(_Dates):
    operation: Literal["get_historical_search_volume"] = Field("get_historical_search_volume", json_schema_extra={"ui:hidden": True})
    keyword: str = Field(..., min_length=1)


class Products(_Page):
    operation: Literal["list_products"] = Field("list_products", json_schema_extra={"ui:hidden": True})
    sort: Literal['name', '-name', 'category', '-category', 'revenue', '-revenue', 'sales', '-sales', 'price', '-price', 'rank', '-rank', 'reviews', '-reviews', 'lqs', '-lqs', 'sellers', '-sellers'] = 'name'
    product_tiers: list[Literal['oversize', 'standard']] | None = Field(None, description='Filter by product tier')
    seller_types: list[Literal['amz', 'fba', 'fbm']] | None = Field(None, description='Filter by seller type (e.g. amz for Amazon, fba for fulfillment by amazon, fbm for fulfillment by merchant)')
    categories: list[str] | None = Field(None)
    include_keywords: list[TitleKeyword] | None = Field(None, max_length=100, description='Filter by title keywords or by ASINs to include')
    exclude_keywords: list[TitleKeyword] | None = Field(None, max_length=100, description='Filter by title keywords or by ASINs to exclude')
    exclude_top_brands: bool | None = Field(None, description='Whether to exclude top brands')
    exclude_unavailable_products: bool | None = Field(None, description='Whether to exclude unavailable products')
    min_price: float | None = Field(None, description='Minimum price')
    max_price: float | None = Field(None, description='Maximum price')
    min_net: float | None = Field(None, description='Minimum price less FBA fees')
    max_net: float | None = Field(None, description='Maximum price less FBA fees')
    min_rank: int | None = Field(None, description='Minimum best seller rank')
    max_rank: int | None = Field(None, description='Maximum best seller rank')
    min_sales: int | None = Field(None, description='Minimum monthly estimated sales')
    max_sales: int | None = Field(None, description='Maximum monthly estimated sales')
    min_revenue: float | None = Field(None, description='Minimum monthly estimated revenue')
    max_revenue: float | None = Field(None, description='Maximum monthly estimated revenue')
    min_reviews: int | None = Field(None, description='Minimum number of reviews')
    max_reviews: int | None = Field(None, description='Maximum number of reviews')
    min_rating: float | None = Field(None, ge=1, le=5, description='Minimum star rating (1 to 5)')
    max_rating: float | None = Field(None, ge=1, le=5, description='Maximum star rating (1 to 5)')
    min_weight: float | None = Field(None, description='Minimum weight (in lbs)')
    max_weight: float | None = Field(None, description='Maximum weight (in lbs)')
    min_sellers: int | None = Field(None, description='Minimum number of sellers (total of FBA, FBM, AMZ sellers)')
    max_sellers: int | None = Field(None, description='Maximum number of sellers (total of FBA, FBM, AMZ sellers)')
    min_lqs: float | None = Field(None, ge=1, le=10, description='Minimum LQS. A grade based off an in-house algorithm factoring in the quality of title, bullet points, photos, and description.')
    max_lqs: float | None = Field(None, ge=1, le=10, description='Maximum LQS. A grade based off an in-house algorithm factoring in the quality of title, bullet points, photos, and description.')
    min_updated_at: str | None = Field(None, min_length=1, description='Minimum updated_at date for a product in format YYYY-MM-DD.')
    max_updated_at: str | None = Field(None, min_length=1, description='Maximum updated_at date for a product in format YYYY-MM-DD.')


class SalesEstimates(_Dates):
    operation: Literal["get_sales_estimates"] = Field("get_sales_estimates", json_schema_extra={"ui:hidden": True})
    asin: ASIN


class ShareOfVoice(_Input):
    operation: Literal["get_share_of_voice"] = Field("get_share_of_voice", json_schema_extra={"ui:hidden": True})
    keyword: str = Field(..., min_length=1)


Operation = Annotated[Union[KeywordsByAsin, KeywordsByKeyword, HistoricalSearchVolume, Products, SalesEstimates, ShareOfVoice], Field(discriminator="operation")]


class JunglescoutConfig(NodeConfig[Operation, JunglescoutAPIKeyCredential]):
    pass


ROUTES = {'list_keywords_by_asin': ('POST', '/api/keywords/keywords_by_asin_query'), 'list_keywords_by_keyword': ('POST', '/api/keywords/keywords_by_keyword_query'), 'get_historical_search_volume': ('GET', '/api/keywords/historical_search_volume'), 'list_products': ('POST', '/api/product_database_query'), 'get_sales_estimates': ('GET', '/api/sales_estimates_query'), 'get_share_of_voice': ('GET', '/api/share_of_voice')}


class JunglescoutNode(WorkflowNode):
    integration_type = "automation-junglescout"
    connection_evidence = ConnectionEvidence(
        noun="product research results", operation="list_products",
        operation_arguments={"page_size": 1}, proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return JunglescoutConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Jungle Scout API key")
        op = self.config.config
        credential = self.config.credentials
        method, path = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        params = {"marketplace": values.pop("marketplace", credential.marketplace)}
        if isinstance(op, _Page):
            params["page[size]"] = values.pop("page_size")
            cursor = values.pop("page_cursor", None)
            if cursor is not None:
                params["page[cursor]"] = cursor
            params["sort"] = values.pop("sort")
        kwargs = {}
        if method == "POST":
            kwargs["json"] = {"data": {"type": path.rsplit("/", 1)[1], "attributes": values}}
        else:
            params.update(values)
        headers = {"Authorization": credential.key_name + ":" + credential.api_key,
                   "X-API-Type": "junglescout", "Accept": MEDIA_TYPE, "Content-Type": "application/vnd.api+json"}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, params=params, headers=headers, **kwargs)
        # Keep provider error text for connection verdicts; redact credentials.
        def redact(value):
            if isinstance(value, str):
                return value.replace(credential.api_key, "[redacted]").replace(credential.key_name, "[redacted]")
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items()}
            return value
        if response.status_code != 200:
            try:
                errors = response.json().get("errors", [])
                message = "; ".join(str(e.get("detail") or e.get("title") or "") for e in errors)
            except (ValueError, AttributeError, TypeError):
                message = ""
            output = {"status": "error", "success": False, "http_status": response.status_code,
                      "message": redact(message) or f"Jungle Scout returned HTTP {response.status_code}"}
        else:
            body = response.json()
            if not isinstance(body, dict) or "errors" in body or not isinstance(body.get("data"), (list, dict)):
                raise ValueError("Expected Jungle Scout research data")
            data = body["data"]
            rows = data if isinstance(data, list) else [data]
            if any(not isinstance(row, dict) or not isinstance(row.get("attributes"), dict) for row in rows):
                raise ValueError("Expected Jungle Scout resource attributes")
            # Never follow a response URL. Extract just the server's opaque cursor.
            next_link = (body.get("links") or {}).get("next")
            cursor = None
            if isinstance(next_link, str):
                cursor = parse_qs(urlsplit(next_link).query).get("page[cursor]", [None])[0]
            output = redact({"status": "success", "success": True, "data": data,
                             "meta": body.get("meta", {}), "next_page_cursor": cursor, "has_more": bool(cursor), "identity_verified": False})
        await self.emit(output)
        return output
