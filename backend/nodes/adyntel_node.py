"""Adyntel API 1.0.0: ad intelligence searches and Shopping job creation/status.

Each operation sends one request. Continuations and async job IDs stay in data;
there is no automatic retry, pagination, polling or creative download.
Contract: https://openapi.gitbook.com/o/tACGR0zGPyCSfzrVHPn6/spec/existing-endpoints.json
"""
from datetime import date
import re
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class AdyntelAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Adyntel API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://platform.adyntel.com",
            "x-credential-instructions": "Copy your API key from your Adyntel profile under Integrations and enter the same account email. NoClick sends both in JSON to api.adyntel.com. Connecting searches TikTok for the documented keyword toys to check API reachability and can consume one credit; it does not establish account identity. Searches and Shopping job creation use Adyntel credits. Provider-side all-ads requests can use many credits and cannot be stopped."})
    credential_type: Literal["adyntel_api_key"] = Field("adyntel_api_key", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., title="Account email", min_length=3, max_length=320)
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without whitespace or a header")
        return value

    @field_validator("email", mode="before")
    @classmethod
    def account_email(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value.strip()):
            raise ValueError("Enter your Adyntel account email")
        return value.strip()


class AdyntelInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("company_domain", check_fields=False)
    @classmethod
    def domain(cls, value):
        if value is not None and (value.startswith("www.") or not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value)):
            raise ValueError("Use a company domain without https://, www or a path")
        return value

    @field_validator("webhook_url", "facebook_url", check_fields=False)
    @classmethod
    def url(cls, value):
        if value is not None:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Use a full HTTP or HTTPS URL without credentials")
        return value

    @model_validator(mode="after")
    def provider_requirements(self):
        if self.operation == "search_facebook_ads" and not (self.facebook_url or self.company_domain):
            raise ValueError("Provide facebook_url or company_domain")
        if self.operation == "search_linkedin_ads" and not any((self.linkedin_page_id, self.company_domain, self.linkedin_page_ids, self.company_domains)):
            raise ValueError("Provide a LinkedIn page ID or company domain (single or batch)")
        if self.operation in {"search_facebook_ads", "search_google_ads", "search_linkedin_ads"} and self.all_ads and not self.webhook_url:
            raise ValueError("All ads requires a webhook URL and can consume many credits")
        if self.operation == "search_linkedin_keywords":
            for value in (self.startDate, self.endDate):
                if value is not None:
                    try:
                        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                            raise ValueError()
                        date.fromisoformat(value)
                    except ValueError:
                        raise ValueError("Use a valid YYYY-MM-DD date") from None
            if self.dateOption == "custom-date-range" and not (self.startDate and self.endDate):
                raise ValueError("A custom date range requires startDate and endDate")
            if self.startDate and self.endDate and self.startDate > self.endDate:
                raise ValueError("startDate must not be after endDate")
        return self


class SearchFacebookAdsConfig(AdyntelInput):
    """Facebook & Instagram Ads."""
    operation: Literal['search_facebook_ads'] = Field('search_facebook_ads', json_schema_extra={"ui:hidden": True})
    facebook_url: str | None = Field(None, min_length=1, description='Facebook page url (needs to start with https://)')
    company_domain: str | None = Field(None, min_length=1, description='Company website Use a bare domain without www, a protocol or a path.')
    country_code: str | None = Field(None, min_length=1, description='Parameter used to filter results for a specific country.')
    continuation_token: str | None = Field(None, min_length=1, description='Token used to grab the next set of ads')
    media_type: Literal['image', 'meme', 'image_and_meme', 'video'] | None = Field(None, description='Parameter used to filter results for a specific type of media.')
    active_status: Literal['inactive', 'all'] | None = Field(None, description='This filters the search in the ad library by active, inactive or all ads.')
    all_ads: bool | None = Field(None, description='This will automatically use the continuation_token and scrape all the pages, returning all available ads.')
    webhook_url: str | None = Field(None, min_length=1, description='Webhook URL where the data will be returned')

class SearchGoogleAdsConfig(AdyntelInput):
    """Google Ads."""
    operation: Literal['search_google_ads'] = Field('search_google_ads', json_schema_extra={"ui:hidden": True})
    company_domain: str = Field(..., min_length=1, description='Company website Use a bare domain without www, a protocol or a path.')
    media_type: Literal['text', 'image', 'video'] | None = Field(None, description='Filter results based on media type. Possible values: text, image, video.')
    continuation_token: str | None = Field(None, min_length=1, description='Token used to grab the next set of ads')
    all_ads: bool | None = Field(None, description='This will automatically use the continuation_token and scrape all the pages, returning all available ads. Works only with a webhook_url as it needs a place to send each page, one by one. Warning: use this cautiously because there is no way of stopping it. If you use this on a domain that runs 10000 ads, it will try to scrape all the ads and it will use the credits (one page = one credit)')
    extract_text: bool | None = Field(None, description='Extract text content from ad creatives')
    webhook_url: str | None = Field(None, min_length=1, description='Webhook URL for async delivery')
    data_provider: Literal['rapidapi', 'apify'] | None = Field(None, description='Data provider to use')

class SearchLinkedInAdsConfig(AdyntelInput):
    """LinkedIn Ads."""
    operation: Literal['search_linkedin_ads'] = Field('search_linkedin_ads', json_schema_extra={"ui:hidden": True})
    linkedin_page_id: str | None = Field(None, min_length=1, description='LinkedIn Page ID')
    company_domain: str | None = Field(None, min_length=1, description='Company website Use a bare domain without www, a protocol or a path.')
    linkedin_page_ids: list[str] | None = Field(None, description='Multiple LinkedIn page IDs for batch mode')
    company_domains: list[str] | None = Field(None, description='Multiple company domains for batch mode')
    continuation_token: str | None = Field(None, min_length=1, description='Token used to grab the next set of ads')
    extract: str | None = Field(None, min_length=1, description="Extract specific data. Use 'number_of_ads' to return only the ad count.")
    all_ads: bool | None = Field(None, description='This will automatically use the continuation_token and scrape all the pages, returning all available ads. Works only with a webhook_url as it needs a place to send each page, one by one. Warning: use this cautiously because there is no way of stopping it. If you use this on a domain that runs 10000 ads, it will try to scrape all the ads and it will use the credits (one page = one credit)')
    live_ads: bool | None = Field(None, description='Only return currently active ads')
    webhook_url: str | None = Field(None, min_length=1, description='Webhook URL where the data will be returned')
    data_provider: Literal['rapidapi', 'apify'] | None = Field(None, description='Data provider to use')

class SearchLinkedInKeywordsConfig(AdyntelInput):
    """LinkedIn Keyword Search."""
    operation: Literal['search_linkedin_keywords'] = Field('search_linkedin_keywords', json_schema_extra={"ui:hidden": True})
    keyword: str = Field(..., min_length=1, description='Company website')
    country: str | None = Field(None, min_length=1, description='The 2-digit country code')
    dateOption: Literal['current-month', 'current-year', 'last-30-days', 'last-year', 'custom-date-range'] | None = Field(None, description='Valid options: current-month, current-year, custom-date-range, last-30-days, last-year or custom-date-range')
    startDate: str | None = Field(None, min_length=1, description='YYYY-MM-DD format (e.g. 2026-01-15)')
    endDate: str | None = Field(None, min_length=1, description='YYYY-MM-DD format (e.g. 2026-01-15)')
    continuation_token: str | None = Field(None, min_length=1, description='A token that you can use to scrape the next page')

class SearchMetaKeywordsConfig(AdyntelInput):
    """Meta Ad Search."""
    operation: Literal['search_meta_keywords'] = Field('search_meta_keywords', json_schema_extra={"ui:hidden": True})
    keyword: str = Field(..., min_length=1, description='The keyword you want to use in your search')
    country_code: str | None = Field(None, min_length=1, description='To limit results to one specific country')
    continuation_token: str | None = Field(None, min_length=1, description='Token for paginating through results')
    all_ads: bool | None = Field(None, description='Return all ads (auto-paginate)')

class CreateGoogleShoppingSearchConfig(AdyntelInput):
    """Google Shopping Ads."""
    operation: Literal['create_google_shopping_search'] = Field('create_google_shopping_search', json_schema_extra={"ui:hidden": True})
    company_domain: str = Field(..., min_length=1, description='Company website Use a bare domain without www, a protocol or a path.')
    shopping: bool | None = Field(None, description='When true, use Railway parser for direct synchronous results. When false, use DataForSEO (async, poll with /google_shopping_status).')

class GetGoogleShoppingStatusConfig(AdyntelInput):
    """Google Shopping Status."""
    operation: Literal['get_google_shopping_status'] = Field('get_google_shopping_status', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='The id you received as response')

class SearchTikTokAdsConfig(AdyntelInput):
    """TikTok Ad Search."""
    operation: Literal['search_tiktok_ads'] = Field('search_tiktok_ads', json_schema_extra={"ui:hidden": True})
    keyword: str = Field(..., min_length=1, description='Your search query')
    country_code: str | None = Field(None, min_length=1, description='Use if you want to limit the search to only one country')

class GetTikTokAdDetailsConfig(AdyntelInput):
    """TikTok Ad Details."""
    operation: Literal['get_tiktok_ad_details'] = Field('get_tiktok_ad_details', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='Ad id')

class GetDomainKeywordsConfig(AdyntelInput):
    """Paid vs Organic Keywords."""
    operation: Literal['get_domain_keywords'] = Field('get_domain_keywords', json_schema_extra={"ui:hidden": True})
    company_domain: str = Field(..., min_length=1, description='Company website (without www or http) Use a bare domain without www, a protocol or a path.')
    language: str | None = Field(None, min_length=1, description='Language for keyword results')
    limit: int | None = Field(None, description='Number of results to return')

AdyntelConfig = Annotated[Union[SearchFacebookAdsConfig, SearchGoogleAdsConfig, SearchLinkedInAdsConfig, SearchLinkedInKeywordsConfig, SearchMetaKeywordsConfig, CreateGoogleShoppingSearchConfig, GetGoogleShoppingStatusConfig, SearchTikTokAdsConfig, GetTikTokAdDetailsConfig, GetDomainKeywordsConfig], Field(discriminator="operation")]


class AdyntelFullConfig(NodeConfig[AdyntelConfig, AdyntelAPIKeyCredential]):
    pass


ROUTES = {'search_facebook_ads': '/facebook', 'search_google_ads': '/google', 'search_linkedin_ads': '/linkedin', 'search_linkedin_keywords': '/linkedin-keyword-search', 'search_meta_keywords': '/facebook_ad_search', 'create_google_shopping_search': '/google_shopping', 'get_google_shopping_status': '/google_shopping_status', 'search_tiktok_ads': '/tiktok_search', 'get_tiktok_ad_details': '/tiktok_ad_details', 'get_domain_keywords': '/domain-keywords'}


class AdyntelNode(WorkflowNode):
    integration_type = "automation-adyntel"
    connection_evidence = ConnectionEvidence(
        noun="Adyntel API access", operation="search_tiktok_ads",
        operation_arguments={"keyword": "toys"}, proves="reachability")

    @classmethod
    def get_config_model(cls):
        return AdyntelFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect your Adyntel account email and API key")
        credential = self.config.credentials
        op = self.config.config
        body = op.model_dump(exclude_none=True, exclude={"operation"})
        body.update(email=credential.email, api_key=credential.api_key)
        async with guarded_async_client(timeout=90, follow_redirects=False, trust_env=False) as client:
            response = await client.request("POST", "https://api.adyntel.com" + ROUTES[op.operation],
                headers={"Accept": "application/json"}, json=body)
        if len(response.content) > 20_000_000:
            raise ValueError("Adyntel response exceeds the content limit")
        if response.status_code == 204 and op.operation == "get_google_shopping_status":
            output = {"status": "success", "http_status": 204, "data": {"ads": []}}
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Adyntel returned a non-JSON response") from None

            def redact(value):
                if isinstance(value, str):
                    return value.replace(credential.api_key, "[redacted]")
                if isinstance(value, list):
                    return [redact(item) for item in value]
                if isinstance(value, dict):
                    return {redact(k): redact(v) for k, v in value.items()}
                return value

            data = redact(data)
            if not isinstance(data, dict):
                raise ValueError("Adyntel returned an unexpected JSON envelope")
            allowed = {200, 202} if op.operation in {"create_google_shopping_search", "get_google_shopping_status"} else {200}
            failed = (response.status_code not in allowed or bool(data.get("error"))
                or bool(data.get("detail")) or data.get("status") in ("error", "failed"))
            if op.operation == "search_tiktok_ads":
                failed = failed or data.get("code", 0) != 0
                if not failed and not isinstance(data.get("data"), list):
                    raise ValueError("Adyntel TikTok search response is missing its data list")
            output = {"status": "error" if failed else "success", "http_status": response.status_code,
                "data": data, **({"error": data} if failed else {})}
        await self.emit(output)
        return output
