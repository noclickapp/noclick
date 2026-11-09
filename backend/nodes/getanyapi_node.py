"""Getanyapi wallet reads and fixed, normalized data runs.

Contract: https://api.getanyapi.com/openapi.json, version 1.0.0.
Run operations incur wallet charges. No automatic retries or implicit polling.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.getanyapi.com"


class GetanyapiApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Getanyapi API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://getanyapi.com/dashboard",
        "x-credential-instructions": "Paste an existing AnyAPI key from your dashboard. NoClick sends it as a Bearer token to api.getanyapi.com. Connecting reads your USD wallet balance for free. Run operations charge this wallet; use a key that permits the operations you need.",
    })
    credential_type: Literal["getanyapi_api_key"] = Field("getanyapi_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Shape(_Input):
    fields: str | None = Field(None, description="Comma-separated result item keys; dotted paths are supported.")
    max_items: int | None = Field(None, ge=0, description="Cap returned rows; does not reduce cost.")
    summary: bool | None = Field(None, description="Return a structural outline; does not reduce cost.")
    jq: str | None = Field(None, description="Reshape the output envelope with jq; does not reduce cost.")


class _Run(_Shape):
    max_cost_usd: str | None = Field(None, description="Maximum USD price for this call, for example 0.05. Omit to accept the normal price.")
    idempotency_key: str | None = Field(None, min_length=1, max_length=255, description="Wallet idempotency key scoped to this customer for 24 hours. Reuse only for the same request.")
    timeout_seconds: int = Field(180, ge=5, le=600, description="Client timeout. Inspect Get API latency before selecting it; a timeout does not prove a run was not charged.")
    source: list[str] | None = Field(None, description="Optional. Source ids to prefer, in order, taken from this endpoint's `lanes[].source.id` in /catalog or /apis. Omit it and the cheapest source serves, with automatic failover. Listed sources are tried first in the order given, then the others, unless `allowFallbacks` is false. A single source with `allowFallbacks` false is served only by that source at its price, quoted and charged exactly, with no failover. The price is that of the dearest source that may serve. An id that does not serve this endpoint is rejected as invalid input with no charge; a listed source that is not serving right now is refused with no charge, so omit `source` to be served by another. On a paginated walk, later pages must include the source that served page one, or omit `source`.")
    allowFallbacks: bool | None = Field(None, description='Optional, default true. When false, only the sources listed in `source` may serve; the request is refused with no charge if none of them can. When true, the listed sources are tried first and any other source may serve after them, at the normal price.')
    ignoreSources: list[str] | None = Field(None, description="Optional. Source ids to skip for this request, taken from this endpoint's `lanes[].source.id`. The cheapest remaining source serves and the price is that of the dearest remaining source. An id that does not serve this endpoint, or that is also in `source`, is rejected as invalid input with no charge; skipping every source is rejected the same way.")
    preferLatencyUnderMs: int | None = Field(None, ge=1, description="Optional; omit it and routing is unchanged, with the cheapest source serving. Prefer sources whose typical response time (median over the trailing 30 days, as published on this endpoint's lane health) is under this many milliseconds; among those, the cheapest serves. This can raise your price: when the cheapest source misses the target, a faster and dearer one serves, and you are quoted and charged its price. If no source is that fast the request is still served, by whichever source offers the best speed for its price - it is never refused for being slow. Sources we have not timed are tried last. This is a preference, not a guarantee: the median describes past requests and is not a ceiling on this one, and it excludes any wait this request itself asks for. On a paginated walk it applies to the first page only: later pages stay with the source that page chose, at the price it was quoted.")

    @field_validator("idempotency_key")
    @classmethod
    def header_value(cls, value):
        if value is not None and (not value.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Use an ASCII idempotency key without control characters")
        return value


class BrowseCatalog(_Input):
    operation: Literal['browse_catalog'] = Field('browse_catalog', title='Browse the API catalog', json_schema_extra={"ui:hidden": True})
    category: str | None = Field(None, description="Restrict the response to one category, using an entry's `category`.")


class SearchCatalog(_Input):
    operation: Literal['search_catalog'] = Field('search_catalog', title='Search the API catalog', json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, description='What you need, in your own words. Long queries are truncated before ranking.')
    category: str | None = Field(None, description="Restrict the response to one category, using an entry's `category`.")
    platform: str | None = Field(None, description="Restrict results to one platform, using a result's `platformId`.")
    limit: int | None = Field(None, ge=1, description="Maximum results in this response. Omit it for the ranked default. A value above the server's maximum is reduced to it rather than rejected, and `total` still reports how many matched.")

    @model_validator(mode="after")
    def query_or_scope(self):
        if not any(v and v.strip() for v in (self.q, self.category, self.platform)):
            raise ValueError("Supply a query, category or platform")
        return self


class ListApis(_Input):
    operation: Literal['list_apis'] = Field('list_apis', title='List the APIs you can run', json_schema_extra={"ui:hidden": True})
    category: str | None = Field(None, description="Restrict the response to one category, using an entry's `category`.")


class GetApi(_Input):
    operation: Literal['get_api'] = Field('get_api', title='Get one API', json_schema_extra={"ui:hidden": True})
    sku: str = Field(..., description="The API's slug, as published by discovery (for example `reddit.search`).")


class GetBalance(_Input):
    operation: Literal['get_balance'] = Field('get_balance', title='Get your wallet balance', json_schema_extra={"ui:hidden": True})


class GetRequest(_Input):
    operation: Literal['get_request'] = Field('get_request', title='Get a request', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., description="Customer-owned request UUID returned by a run.")


class GetResult(_Shape):
    operation: Literal['get_result'] = Field('get_result', title='Re-read a cached result for free', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='The `resultId` returned on a prior run response envelope.')


class WebScrape(_Run):
    operation: Literal['web_scrape'] = Field('web_scrape', title='Web Scrape', description="Paid run: charges your AnyAPI USD wallet.", json_schema_extra={"ui:hidden": True})
    blockAds: bool | None = Field(None, description='When true (upstream default), strip ad and cookie-consent elements before capture. Set false to keep them.')
    excludeTags: list[str] | None = Field(None, description='CSS selectors to drop before capture (for example ["nav", "footer", ".ads"]). Applied after includeTags.')
    formats: list[Literal['markdown', 'html', 'rawHtml']] | None = Field(None, description='Which representations of the page to return. Any combination of: markdown (page content as Markdown), html (the page HTML exactly as the browser received it, including head and script tags). Each requested format is returned under the matching output field. Defaults to both. rawHtml is a deprecated alias of html, returned under a rawHtml field for callers that predate the rename; send html instead.')
    includeTags: list[str] | None = Field(None, description='CSS selectors to keep. When set, only content matching these selectors is captured (for example ["article", "main"] or ["#content"]).')
    mobile: bool | None = Field(None, description='When true, render the page with a mobile viewport and user agent instead of desktop. Some sites serve materially different content to mobile.')
    onlyMainContent: bool | None = Field(None, description='When true, return only the main article content, stripping navigation, headers, footers, and other boilerplate. Defaults to false to capture the full page.')
    requireFields: list[Literal['statusCode']] | None = Field(None, description='Optional; omit it and routing is unchanged, with the cheapest source serving. Name the output fields this request must be able to return, for example `statusCode`, and it is served only by a source that returns every one of them. Fields you do not name are still returned whenever the serving source has them. This can raise your price: when the cheapest source cannot return a named field, a dearer source serves, and you are quoted and charged its price. A named field can still be absent on a record that genuinely lacks it. Naming a combination that no single source returns together is refused as invalid input, with no charge. A source that reports a field only in some cases, such as only when the website answered with an error, does not count as returning it.')
    url: str = Field(..., min_length=1, description='The full web address of the page to scrape, including its domain, for example https://example.com. The https:// prefix is optional.')
    waitFor: int | None = Field(None, ge=0, le=15000, description='Milliseconds to wait for the page to finish rendering before capture. Use this for JavaScript-heavy pages or single-page apps whose content loads after the initial paint. Capped at 15000 to stay within the request timeout. This wait is time you asked us to spend, so your response takes this much longer, and it is excluded from the latency published for this endpoint. If every provider that can wait fails, the page may still be returned, captured without the wait.')


class WebMap(_Run):
    operation: Literal['web_map'] = Field('web_map', title='Web Map', description="Paid run: charges your AnyAPI USD wallet.", json_schema_extra={"ui:hidden": True})
    includeSubdomains: bool | None = Field(None, description='When true (upstream default), include URLs on subdomains of the target (for example docs.example.com when mapping example.com). Set false to return only URLs on the exact host.')
    limit: int | None = Field(None, description='Maximum number of links to return.')
    search: str | None = Field(None, description='Optional term that orders the returned links by relevance.')
    sitemap: Literal['include', 'skip', 'only'] | None = Field(None, description="How to use the site's sitemap.xml when discovering URLs. 'include' (upstream default) merges sitemap URLs with links found by crawling; 'only' returns just the URLs listed in the sitemap (fastest and most authoritative); 'skip' ignores the sitemap and discovers URLs by crawling links. Omit to use 'include'.")
    url: str = Field(..., description='The base URL of the site to map into a list of links.')


class WebScreenshot(_Run):
    operation: Literal['web_screenshot'] = Field('web_screenshot', title='Website Screenshot', description="Paid run: charges your AnyAPI USD wallet.", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., description='The full URL of the page to capture.')
    viewportWidth: int | None = Field(None, description='Browser viewport width in pixels (e.g. 1280).')


class GoogleSearch(_Run):
    operation: Literal['google_search'] = Field('google_search', title='Google Search', description="Paid run: charges your AnyAPI USD wallet.", json_schema_extra={"ui:hidden": True})
    autocorrect: bool | None = Field(None, description='Toggle Google spelling autocorrect (default true). Set false to search the exact query without correction.')
    cursor: str | None = Field(None, min_length=1, description="Deprecated: send page instead. A continuation token from an earlier response's nextCursor is still accepted and still continues on the source that issued it; page is ignored when cursor is sent alongside it.")
    gl: str | None = Field(None, description='Two-letter country code for result localization (e.g. us, gb, de).')
    hl: str | None = Field(None, description='Two-letter interface and results language code (e.g. en, es, de).')
    limit: int | None = Field(None, ge=1, le=100, description='Page size to ask for. Google returns about 10 organic results per page and stopped honoring larger counts in September 2025, so a limit above 10 still returns about 10. Some sources return their whole page of about 10 whatever limit says: a page is never trimmed after the call, so nextCursor always continues exactly where this response ended. To go deeper, send page (about 10 results per page, each billed as a request) or use google.search_100, which returns up to 100 ranked results in a single call for one flat charge and is cheaper past roughly 20 results. Price is flat per request.')
    location: str | None = Field(None, description="Fine-grained location to localize results to, more specific than the country-level gl. Send it as an Active Canonical Name from Google's geo-target list: place, then each parent region, then country, with no space after each comma, e.g. 'New York,New York,United States', 'Austin,Texas,United States', 'London,England,United Kingdom'. Common variations are translated to that name when they point to exactly one place: spaces after commas, missing accents, a US state abbreviation ('Orlando, FL, United States'), or a skipped region ('Sydney, Australia'). A value that names no place, or more than one, is rejected rather than quietly searched from somewhere else.")
    page: int | None = Field(None, ge=1, description='Which page of about 10 organic results to return, starting at 1. Send page 2, 3, ... to walk deeper; each page is billed as one request and any source can serve any page. Replaces cursor.')
    query: str = Field(..., description='The Google search query.')
    requireCursor: bool | None = Field(None, description='Deprecated. Every source for this search returns a nextCursor, so this changes nothing about the price or which source serves you; it stays accepted so callers that already send it keep working.')
    timeframe: Literal['1h', '1d', '7d', '1y', 'all'] | None = Field(None, description='Restrict results to a recent time window: 1h, 1d, 7d, 1y, or all. Default all (no time restriction).')


class BingSearch(_Run):
    operation: Literal['bing_search'] = Field('bing_search', title='Bing Search', description="Paid run: charges your AnyAPI USD wallet.", json_schema_extra={"ui:hidden": True})
    country: str | None = Field(None, description='ISO-3166 alpha-2 country Bing searches from, e.g. US, GB, DE. Bing ranks and localizes results for that country and its main language. Common countries are served by every source; a country only some sources cover is served by those, and one no source covers is refused with no charge.')
    limit: int | None = Field(None, ge=1, le=10, description='Maximum number of organic results to return (1-10, default 10). Bing serves about 10 organic results per page, and some queries carry fewer.')
    query: str = Field(..., min_length=1, description='The Bing search query.')
    requireFields: list[Literal['answer', 'peopleAlsoAsk', 'publishedUtc', 'question', 'siteName']] | None = Field(None, description='Optional; omit it and routing is unchanged, with the cheapest source serving. Name the output fields this request must be able to return, for example `siteName` or `publishedUtc`, and it is served only by a source that returns every one of them. Fields you do not name are still returned whenever the serving source has them. This can raise your price: when the cheapest source cannot return a named field, a dearer source serves, and you are quoted and charged its price. A named field can still be absent on a result that genuinely lacks it. Naming a combination that no single source returns together is refused as invalid input, with no charge.')


class BraveSearch(_Run):
    operation: Literal['brave_search'] = Field('brave_search', title='Brave Search', description="Paid run: charges your AnyAPI USD wallet.", json_schema_extra={"ui:hidden": True})
    country: Literal['AR', 'AU', 'AT', 'BE', 'BR', 'CA', 'CL', 'CN', 'DK', 'FI', 'FR', 'DE', 'GR', 'HK', 'IN', 'ID', 'IT', 'JP', 'KR', 'MY', 'MX', 'NL', 'NZ', 'NO', 'PL', 'PT', 'PH', 'RU', 'SA', 'SG', 'ZA', 'ES', 'SE', 'CH', 'TW', 'TR', 'GB', 'US'] | None = Field(None, description='ISO-3166 alpha-2 country Brave searches from, e.g. US, GB, DE. Brave ranks and localizes results for that country. Only the countries Brave offers are accepted; US is served by every source and the others by the sources that can target them.')
    limit: int | None = Field(None, ge=1, le=20, description='Maximum number of organic results to return (1-20, default 20). Brave serves about 20 organic results per page, and some queries carry fewer.')
    page: int | None = Field(None, ge=1, le=10, description='Which page of Brave results to return, starting at 1 (up to 10); a page holds about 20 results. Each page is billed as one request. Pages after the first are served only for country US, by the one source that continues each page exactly where the last ended. A limit below the page size drops the rest of that page, so keep the default limit to walk every result.')
    query: str = Field(..., min_length=1, description='The Brave search query.')
    requireFields: list[Literal['durationSeconds', 'image', 'publishedUtc', 'relatedSearches', 'source', 'videos']] | None = Field(None, description='Optional; omit it and routing is unchanged, with the cheapest source serving. Name the output fields this request must be able to return, for example `relatedSearches` or `publishedUtc`, and it is served only by a source that returns every one of them. Fields you do not name are still returned whenever the serving source has them. This can raise your price: when the cheapest source cannot return a named field, a dearer source serves, and you are quoted and charged its price. A named field can still be absent on a record that genuinely lacks it. Naming a combination that no single source returns together is refused as invalid input, with no charge.')


class DuckduckgoSearch(_Run):
    operation: Literal['duckduckgo_search'] = Field('duckduckgo_search', title='DuckDuckGo Search', description="Paid run: charges your AnyAPI USD wallet.", json_schema_extra={"ui:hidden": True})
    country: Literal['AR', 'AU', 'AT', 'BE', 'BR', 'BG', 'CA', 'CL', 'CN', 'CO', 'HR', 'CZ', 'DK', 'EE', 'FI', 'FR', 'DE', 'GR', 'HK', 'HU', 'IS', 'IN', 'ID', 'IE', 'IL', 'IT', 'JP', 'KR', 'LV', 'LT', 'MY', 'MX', 'NL', 'NZ', 'NO', 'PK', 'PE', 'PH', 'PL', 'PT', 'RO', 'RU', 'SA', 'SG', 'SK', 'SI', 'ZA', 'ES', 'SE', 'CH', 'TW', 'TH', 'TR', 'US', 'UA', 'GB', 'VN'] | None = Field(None, description="ISO-3166 alpha-2 country DuckDuckGo searches from, e.g. US, GB, DE: DuckDuckGo's region for that country in its main language (Belgium in Dutch, Canada and the US in English, Switzerland in German, Spain in Spanish). Only the countries DuckDuckGo offers are accepted; every country is served by most sources and US, GB and DE by all of them.")
    limit: int | None = Field(None, ge=1, le=10, description='Maximum number of organic results to return (1-10, default 10). DuckDuckGo serves about 10 organic results per page, and some queries carry fewer.')
    page: int | None = Field(None, ge=1, description='Which page of 10 results to return, starting at 1: page 2 returns results 11-20. Each page is billed as one request. Pages after the first are served only for country US, GB or DE, by the one source that continues each page exactly where the last ended. DuckDuckGo can repeat a result from the previous page, so deduplicate on url, and a limit below 10 drops the rest of that page.')
    query: str = Field(..., min_length=1, description='The DuckDuckGo search query.')


class EmailFind(_Run):
    operation: Literal['email_find'] = Field('email_find', title='Email Finder', description="Paid run: charges your AnyAPI USD wallet.", json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., description='Company domain (e.g. acme.com) or company name (e.g. Acme Inc), resolved automatically.')
    firstName: str = Field(..., description="The person's first name (e.g. Jane).")
    surname: str = Field(..., description="The person's last name (e.g. Doe).")


class EmailVerify(_Run):
    operation: Literal['email_verify'] = Field('email_verify', title='Email Verifier', description="Paid run: charges your AnyAPI USD wallet.", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=6, max_length=254, description='The email address to verify (e.g. jane.doe@acme.com). Exactly one @, a dotted domain, no whitespace or angle brackets. Addresses on reserved, never-deliverable TLDs (.invalid, .test, .example, .localhost, .local, .internal, .blink) and HTML/JSON escape artifacts (a u003e prefix) are rejected locally with no charge.')
    requireFields: list[Literal['mxProvider', 'reason']] | None = Field(None, description='Optional; omit it and routing is unchanged, with the cheapest source serving. Name the output fields this request must be able to return, for example `reason`, and it is served only by a source that returns every one of them. Fields you do not name are still returned whenever the serving source has them. This can raise your price: when the cheapest source cannot return a named field, a dearer source serves, and you are quoted and charged its price. A named field can still be absent on a result that genuinely lacks it. Naming a combination that no single source returns together is refused as invalid input, with no charge.')


class LinkedinProfile(_Run):
    operation: Literal['linkedin_profile'] = Field('linkedin_profile', title='LinkedIn Profile', description="Paid run: charges your AnyAPI USD wallet.", json_schema_extra={"ui:hidden": True})
    requireFields: list[Literal['endorsements', 'positions', 'schoolId', 'topSkills', 'workplaceType']] | None = Field(None, description='Optional; omit it and routing is unchanged, with the cheapest source serving. Name the output fields this request must be able to return, for example `topSkills` or `workplaceType`, and it is served only by a source that returns every one of them. Fields you do not name are still returned whenever the serving source has them. This can raise your price: when the cheapest source cannot return a named field, a dearer source serves, and you are quoted and charged its price. A named field can still be absent on a profile that genuinely lacks it. Naming a combination that no single source returns together is refused as invalid input, with no charge.')
    url: str = Field(..., description='Full LinkedIn profile URL.')


class LinkedinCompany(_Run):
    operation: Literal['linkedin_company'] = Field('linkedin_company', title='LinkedIn Company', description="Paid run: charges your AnyAPI USD wallet.", json_schema_extra={"ui:hidden": True})
    requireFields: list[Literal['city', 'companyType', 'foundedOn', 'fundingData', 'line1', 'pageVerified', 'postalCode', 'similarOrganizations']] | None = Field(None, description='Optional; omit it and routing is unchanged, with the cheapest source serving. Name the output fields this request must be able to return, for example `city` or `postalCode`, and it is served only by a source that returns every one of them. Fields you do not name are still returned whenever the serving source has them. This can raise your price: when the cheapest source cannot return a named field, a dearer source serves, and you are quoted and charged its price. A named field can still be absent on a profile that genuinely lacks it. Naming a combination that no single source returns together is refused as invalid input, with no charge.')
    url: str = Field(..., description='Full LinkedIn company page URL.')


class TwitterSearch(_Run):
    operation: Literal['twitter_search'] = Field('twitter_search', title='X / Twitter Search', description="Paid run: charges your AnyAPI USD wallet.", json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, description="Opaque pagination cursor from a previous response's nextCursor. Omit for the first page; pass it to fetch the next page of search results.")
    limit: int | None = Field(None, ge=1, le=50, description='Page size to ask for (1-50, default 20). Some sources honor it; others always return their whole native page of about 20. A page is never trimmed after the call, so follow nextCursor to continue exactly where this response ended.')
    query: str = Field(..., description='Search query using X (Twitter) advanced-search syntax. IMPORTANT: bare terms are ANDed - a tweet must contain EVERY word, so a list of loosely related keywords matches nothing; use one short phrase or OR between alternatives (e.g. \'anyapi OR getanyapi\'). When an operator follows an OR list, put the list in parentheses, e.g. \'(anyapi OR getanyapi) -filter:replies\': without them X applies the operator to the last alternative only, so such a query still runs as X reads it and the response\'s hint carries the corrected query. You can embed X advanced-search operators directly in the query to filter results: from:username and to:username (author or recipient), since:YYYY-MM-DD and until:YYYY-MM-DD (date range), min_faves:N, min_retweets:N, min_replies:N (engagement floors), "exact phrase", -term to exclude, filter:media and filter:links and -filter:replies (content filters), lang:en, near:city, and geocode:lat,long,radius. Examples: \'from:OpenAI\', \'AI agents min_faves:500 -filter:replies\', \'nvidia since:2026-01-01 until:2026-03-01\'. A query with no matches returns an empty items array; prefer the fewest words that identify the topic.')
    queryType: Literal['Latest', 'Top', 'Photos', 'Videos'] | None = Field(None, description="Which posts to return: 'Latest' (newest first, the default), 'Top' (most popular), 'Photos' (newest posts with images), or 'Videos' (newest posts with video). Photos and Videos search your query as written with filter:images or filter:videos added after it, so they cost the same as a Latest search.")
    requireFields: list[Literal['nextCursor']] | None = Field(None, description='Optional; omit it and routing is unchanged, with the cheapest source serving. Name the output fields this request must be able to return, for example `nextCursor`, and it is served only by a source that returns every one of them. Fields you do not name are still returned whenever the serving source has them. This can raise your price: when the cheapest source cannot return a named field, a dearer source serves, and you are quoted and charged its price. A named field can still be absent on a post that genuinely lacks it. Naming a combination that no single source returns together is refused as invalid input, with no charge. On a paginated walk it applies to the first page only; later pages stay with the source that page chose, at the price it was quoted.')
    requireSinglePage: bool | None = Field(None, description='Set true to get up to limit results in one response instead of provider-native pages, served by a bulk provider when needed.')


class YoutubeVideoTranscript(_Run):
    operation: Literal['youtube_video_transcript'] = Field('youtube_video_transcript', title='YouTube Video Transcript', description="Paid run: charges your AnyAPI USD wallet.", json_schema_extra={"ui:hidden": True})
    id: str | None = Field(None, description='YouTube video ID. A Short uses the same ID as any other video.')
    url: str | None = Field(None, description='Full YouTube video URL. Shorts (youtube.com/shorts/...), youtu.be, live, and embed URLs all work.')

    @model_validator(mode="after")
    def video(self):
        if not (self.url or self.id):
            raise ValueError("Supply a YouTube URL or video ID")
        return self


Operation = Annotated[Union[BrowseCatalog, SearchCatalog, ListApis, GetApi, GetBalance, GetRequest, GetResult, WebScrape, WebMap, WebScreenshot, GoogleSearch, BingSearch, BraveSearch, DuckduckgoSearch, EmailFind, EmailVerify, LinkedinProfile, LinkedinCompany, TwitterSearch, YoutubeVideoTranscript], Field(discriminator="operation")]


class GetanyapiConfig(NodeConfig[Operation, GetanyapiApiKeyCredential]):
    pass


ROUTES = {'browse_catalog': ('GET', '/catalog'), 'search_catalog': ('GET', '/catalog/search'), 'list_apis': ('GET', '/v1/apis'), 'get_api': ('GET', '/v1/apis/{sku}'), 'get_balance': ('GET', '/v1/balance'), 'get_request': ('GET', '/v1/requests/{id}'), 'get_result': ('GET', '/v1/results/{id}'), 'web_scrape': ('POST', '/v1/run/web.scrape'), 'web_map': ('POST', '/v1/run/web.map'), 'web_screenshot': ('POST', '/v1/run/web.screenshot'), 'google_search': ('POST', '/v1/run/google.search'), 'bing_search': ('POST', '/v1/run/bing.search'), 'brave_search': ('POST', '/v1/run/brave.search'), 'duckduckgo_search': ('POST', '/v1/run/duckduckgo.search'), 'email_find': ('POST', '/v1/run/email.find'), 'email_verify': ('POST', '/v1/run/email.verify'), 'linkedin_profile': ('POST', '/v1/run/linkedin.profile'), 'linkedin_company': ('POST', '/v1/run/linkedin.company'), 'twitter_search': ('POST', '/v1/run/twitter.search'), 'youtube_video_transcript': ('POST', '/v1/run/youtube.video_transcript')}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    return value


class GetanyapiNode(WorkflowNode):
    integration_type = "automation-getanyapi"
    connection_evidence = ConnectionEvidence(noun="wallet balance", operation="get_balance")

    @classmethod
    def get_config_model(cls):
        return GetanyapiConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Getanyapi API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for field in ("sku", "id"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", quote(values.pop(field), safe=""))
        headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
        timeout = values.pop("timeout_seconds", 30)
        params = {}
        body = None
        if method == "POST":
            for field in ("fields", "max_items", "summary", "jq", "max_cost_usd"):
                if field in values:
                    params[field] = values.pop(field)
            idempotency_key = values.pop("idempotency_key", None)
            if idempotency_key is not None:
                headers["Idempotency-Key"] = idempotency_key
            if op.operation == "email_find":
                values["person"] = {field: values.pop(field) for field in ("firstName", "surname", "domain")}
            body = values
        else:
            params = values
        # Fixed provider origin, redirects disabled, and no implicit retries.
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, headers=headers, params=params, **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("Getanyapi request did not complete; paid run outcome is unknown. Inspect the request before retrying.") from None
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Getanyapi returned an unreadable response; paid run outcome may be unknown") from None
        if not 200 <= response.status_code < 300:
            output = {"status": "error", "http_status": response.status_code, "error": data}
        else:
            if not isinstance(data, dict):
                raise ValueError("Expected a Getanyapi JSON response object")
            output = {"status": "success", "data": data, "http_status": response.status_code}
            if op.operation == "get_balance":
                usd = data.get("usd")
                if type(usd) not in (int, float):
                    raise ValueError("Getanyapi wallet response has no USD balance")
                output["items"] = [{"name": f"USD wallet balance: {usd}"}]
        output = _redact(output, key)
        await self.emit(output)
        return output
