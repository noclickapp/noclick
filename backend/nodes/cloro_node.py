"""Cloro v1 AI answer monitoring, search and asynchronous task operations.

Request models follow the provider's published 1.0.0 contract. Each operation
makes one request; task submission does not imply task completion or delivery.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID
from urllib.parse import quote, quote_plus, urlsplit, parse_qs

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.cloro.dev"
StateCode = Literal['AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'DC', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY']
CountryCode = Literal['AD', 'AE', 'AF', 'AG', 'AI', 'AL', 'AM', 'AO', 'AQ', 'AR', 'AS', 'AT', 'AU', 'AW', 'AX', 'AZ', 'BA', 'BB', 'BD', 'BE', 'BF', 'BG', 'BH', 'BI', 'BJ', 'BL', 'BM', 'BN', 'BO', 'BQ', 'BR', 'BS', 'BT', 'BV', 'BW', 'BY', 'BZ', 'CA', 'CC', 'CD', 'CF', 'CG', 'CH', 'CI', 'CK', 'CL', 'CM', 'CN', 'CO', 'CR', 'CU', 'CV', 'CW', 'CX', 'CY', 'CZ', 'DE', 'DJ', 'DK', 'DM', 'DO', 'DZ', 'EC', 'EE', 'EG', 'EH', 'ER', 'ES', 'ET', 'FI', 'FJ', 'FK', 'FM', 'FO', 'FR', 'GA', 'GB', 'GD', 'GE', 'GF', 'GG', 'GH', 'GI', 'GL', 'GM', 'GN', 'GP', 'GQ', 'GR', 'GS', 'GT', 'GU', 'GW', 'GY', 'HK', 'HM', 'HN', 'HR', 'HT', 'HU', 'ID', 'IE', 'IL', 'IM', 'IN', 'IO', 'IQ', 'IR', 'IS', 'IT', 'JE', 'JM', 'JO', 'JP', 'KE', 'KG', 'KH', 'KI', 'KM', 'KN', 'KP', 'KR', 'KW', 'KY', 'KZ', 'LA', 'LB', 'LC', 'LI', 'LK', 'LR', 'LS', 'LT', 'LU', 'LV', 'LY', 'MA', 'MC', 'MD', 'ME', 'MF', 'MG', 'MH', 'MK', 'ML', 'MM', 'MN', 'MO', 'MP', 'MQ', 'MR', 'MS', 'MT', 'MU', 'MV', 'MW', 'MX', 'MY', 'MZ', 'NA', 'NC', 'NE', 'NF', 'NG', 'NI', 'NL', 'NO', 'NP', 'NR', 'NU', 'NZ', 'OM', 'PA', 'PE', 'PF', 'PG', 'PH', 'PK', 'PL', 'PM', 'PN', 'PR', 'PS', 'PT', 'PW', 'PY', 'QA', 'RE', 'RO', 'RS', 'RU', 'RW', 'SA', 'SB', 'SC', 'SD', 'SE', 'SG', 'SH', 'SI', 'SJ', 'SK', 'SL', 'SM', 'SN', 'SO', 'SR', 'SS', 'ST', 'SV', 'SX', 'SY', 'SZ', 'TC', 'TD', 'TF', 'TG', 'TH', 'TJ', 'TK', 'TL', 'TM', 'TN', 'TO', 'TR', 'TT', 'TV', 'TW', 'TZ', 'UA', 'UG', 'UM', 'US', 'UY', 'UZ', 'VA', 'VC', 'VE', 'VG', 'VI', 'VN', 'VU', 'WF', 'WS', 'XK', 'YE', 'YT', 'ZA', 'ZM', 'ZW']


class CloroAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Cloro API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://dashboard.cloro.dev/api-keys",
        "x-credential-instructions": "Create an API key in your Cloro dashboard and paste it here. All endpoints share this key; Cloro offers no per-key scopes. Monitoring and task submission consume credits; optional formats, extra pages and state targeting can cost more. Connecting only reads your credit balance.",
    })
    credential_type: Literal["cloro_api_key"] = Field("cloro_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(ch.isspace() or ord(ch) < 32 or ord(ch) > 126 for ch in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Request(_Input):
    @model_validator(mode="after")
    def targeting(self):
        data = self.model_dump(exclude_none=True)
        if data.get("state") and data.get("country") != "US":
            raise ValueError("State targeting requires country US")
        if data.get("country") and data.get("gl") and data["country"].lower() != data["gl"].lower():
            raise ValueError("country and gl must agree")
        if data.get("location") and data.get("uule"):
            raise ValueError("Choose location or uule")
        if type(self).__name__ in {"GoogleMonitorRequest", "MonitorGoogle"}:
            if data.get("url"):
                parts = urlsplit(data["url"])
                if parts.scheme not in {"http", "https"} or not re_google_host(parts.hostname) or parts.path != "/search" or not parse_qs(parts.query).get("q") or "tbm" in parse_qs(parts.query):
                    raise ValueError("Use a Google web search URL with a query")
                if any(data.get(k) is not None for k in ("query", "location", "uule", "pages")):
                    raise ValueError("A search URL cannot be combined with query, location, uule or pages")
            elif not data.get("query") or not (data.get("country") or data.get("gl")):
                raise ValueError("Supply query and country/gl, or a Google search URL")
        if type(self).__name__ in {"GoogleNewsMonitorRequest", "MonitorGoogleNews", "AiModeMonitorRequest", "MonitorAiMode"} and not (data.get("country") or data.get("gl")):
            raise ValueError("Supply country or gl")
        if type(self).__name__ in {"BingAiModeMonitorRequest", "MonitorBingAiMode"}:
            if data.get("country") in {"BY", "CN", "IR", "RU", "SY", "VE"}:
                raise ValueError("Bing AI Mode does not support this country")
            if len(quote_plus(data["prompt"])) > 3500:
                raise ValueError("Bing prompt exceeds 3500 URL-encoded characters")
        if type(self).__name__ in {"GoogleGotoRequest", "ResolveGoogleGoto"}:
            parts = urlsplit(data["url"])
            if parts.scheme not in {"http", "https"} or parts.hostname not in {"google.com", "www.google.com"} or parts.path not in {"/goto", "/url"}:
                raise ValueError("Use a Google /goto or /url redirect link")
        return self


# Cloro's own MCP server: agents get its tools through a person's Cloro sign-in.
CloroMcpCredential = mcp_credential("cloro", "https://mcp.cloro.dev/mcp", app="Cloro")
CloroCredential = Union[CloroAPIKeyCredential, CloroMcpCredential]


def re_google_host(host):
    import re
    return bool(host and re.fullmatch(r"(?:www\.)?google\.(?:[a-z]{2,3}|co\.[a-z]{2}|com\.[a-z]{2})", host))

class ChatGPTMonitorRequestInclude(_Request):
    html: bool | None = Field(None, description='Include a URL to the full HTML of the response')
    markdown: bool | None = Field(None, description='Include markdown-formatted response in the result')
    rawResponse: bool | None = Field(None, description="Include ChatGPT's raw response payload. Paid add-on: one flat +2 credits covers any combination of `rawResponse`, `searchQueries`, `ads` and `shopping` ([pricing](/guides/providers#chatgpt-additional-features)).")
    searchQueries: bool | None = Field(None, description='Include the query fan-out ChatGPT used to generate the response. Paid add-on: one flat +2 credits covers any combination of `rawResponse`, `searchQueries`, `ads` and `shopping` ([pricing](/guides/providers#chatgpt-additional-features)).')
    ads: bool | None = Field(None, description='Include ads displayed in ChatGPT response. ChatGPT currently shows ads only in answers to a follow-up prompt, and far more often on the legacy interface: send `prompt` as an array with `legacy: true`. Paid add-on: one flat +2 credits covers any combination of `rawResponse`, `searchQueries`, `ads` and `shopping` ([pricing](/guides/providers#chatgpt-additional-features)).')
    shopping: bool | None = Field(None, description='Include shopping cards and inline products with pricing and offers. Paid add-on: one flat +2 credits covers any combination of `rawResponse`, `searchQueries`, `ads` and `shopping` ([pricing](/guides/providers#chatgpt-additional-features)).')
    productDetails: bool | None = Field(None, description="Add the rationale and reviews from each product's sheet as `productDetails`. Needs `shopping`. +2 credits on top of `shopping`.")


class ChatGPTMonitorRequest(_Request):
    prompt: Union[Annotated[str, Field(min_length=1, max_length=10000)], Annotated[list[Annotated[str, Field(min_length=1, max_length=10000)]], Field(min_length=1, max_length=5)]] = Field(..., description='The prompt to send to ChatGPT, or an array of up to 5 prompts for a multi-turn conversation. With an array, ChatGPT answers the prompts in order, in the same conversation, and `result` is an array with one response for each prompt. Each prompt after the first costs +1 credit ([pricing](/guides/providers#chatgpt-additional-features)).')
    country: CountryCode = Field(..., description='Country/region code for localized response, using ISO 3166-1 alpha-2 country codes.')
    include: ChatGPTMonitorRequestInclude | None = Field(None, description='Optional flags for including additional response formats')
    legacy: bool | None = Field(None, description="Serve ChatGPT's legacy desktop interface instead of the default mobile-web one. The legacy interface streams the answer as an event stream, so `result.model`, `result.searchQueries` and `result.mapSearchQueries` are populated. ChatGPT shows ads far more often on this interface. Best-effort and temporary: OpenAI controls which interface it serves and can retire the legacy one at any time, so a request can still come back in the mobile-web shape. Handle both. Defaults to false.")
    disableWebSearch: bool | None = Field(None, description="Do not force ChatGPT's web search. cloro returns the answer ChatGPT gives on its own, which uses web search only when ChatGPT decides to, so `result.sources`, `result.citationPills` and `result.searchQueries` are often empty. Defaults to false: web search is forced on every request.")
    state: StateCode | None = Field(None)


class GeminiMonitorRequestInclude(_Request):
    markdown: bool | None = Field(None, description='Include markdown-formatted response in the result')
    html: bool | None = Field(None, description='Include HTML-formatted response in the result')
    rawResponse: bool | None = Field(None, description='Include raw streaming response events')


class GeminiMonitorRequest(_Request):
    prompt: Annotated[str, Field(min_length=1, max_length=10000)] = Field(..., description='The prompt to send to Gemini')
    country: CountryCode = Field(..., description='Country/region code for localized response, using ISO 3166-1 alpha-2 country codes.')
    include: GeminiMonitorRequestInclude | None = Field(None, description='Optional flags for including additional response formats')
    state: StateCode | None = Field(None)


class GoogleMonitorRequestIncludeAioverview(_Request):
    markdown: bool | None = Field(None, description='Include AI Overview formatted as markdown in `result.aioverview.markdown`. Only `true` turns it on.')


class GoogleMonitorRequestInclude(_Request):
    html: bool | None = Field(None, description='Include raw HTML response from Google search')
    aioverview: GoogleMonitorRequestIncludeAioverview | None = Field(None, description='Include Google AI Overview in the response. `true`, `{}` and `{"markdown": false}` return the AI Overview without `markdown`. Send `{"markdown": true}` to also get `result.aioverview.markdown`. Paid add-on: one flat +2 credits covers `aioverview` and `paaAioverview`, alone or together ([pricing](/guides/providers#google-search-multi-page-pricing)).')
    paaAioverview: bool | None = Field(None, description='Hydrate AI-Overview-type People Also Ask items with markdown content and sources. Paid add-on: one flat +2 credits covers `aioverview` and `paaAioverview`, alone or together ([pricing](/guides/providers#google-search-multi-page-pricing)). Each hydrated item adds one scraper fetch (typically 1-2 per page), so responses take longer.')
    googleGoto: bool | None = Field(None, description='Ignored since 8th September 2026. Every redirect link now ships as `redirectLink` beside its destination, so both are returned without this flag. Requests still sending it behave as if it were absent.')


class GoogleMonitorRequest(_Request):
    query: Annotated[str, Field(min_length=1, max_length=10000)] | None = Field(None, description="The search query to execute on Google. Required unless you supply 'url' instead — the two are mutually exclusive.")
    url: str | None = Field(None, description="A complete Google web search URL to run instead of building the request from 'query' and the targeting fields. Must be an absolute http(s) URL on a Google web search host (google.com, google.co.uk, www.google.de, ...), with the path '/search' and a non-empty 'q'. Mutually exclusive with 'query', 'location', 'uule' and 'pages' — the URL owns those values. cloro applies a fixed set of query parameters — 'q', 'gl', 'hl', 'uule', 'num' (read as result depth), 'start', 'tbs' and 'safe' — and drops an")
    country: CountryCode | None = Field(None, description="ISO 3166-1 alpha-2 country code for localized search results. See [List of countries](/api-reference/endpoint/countries) for the codes each provider supports. Required in the standard request shape unless you send `gl`. When you supply 'url' instead, country is derived from the URL's 'gl' — pass it explicitly to override that, or when the URL has no 'gl'.")
    gl: str | None = Field(None)
    hl: str | None = Field(None)
    location: str | None = Field(None, description="Google canonical location name for geo-targeted results, in comma-separated format: 'City,Region,Country' (see https://developers.google.com/google-ads/api/reference/data/geotargets for all ~100,000 supported locations). Use alongside 'country' for city-level precision. Mutually exclusive with 'uule' — provide one or the other, not both. Cannot be combined with 'url'. When both `location` and `uule` are omitted, cloro pins results to the country's canonical location (e.g. `Portugal` for `PT`) wh")
    uule: str | None = Field(None, description="Pre-encoded Google UULE string for precise geo-targeting. Use this when you have a pre-built UULE value instead of a location name. Mutually exclusive with 'location' — provide one or the other, not both. Cannot be combined with 'url'; put 'uule' in the URL's query string instead.")
    device: Literal['desktop', 'mobile', 'ios', 'android'] | None = Field(None, description="Device the search is run from. 'desktop' returns the desktop SERP; 'ios' (Safari on iPhone), 'android' (Chrome on Android) and 'mobile' (alias for 'android') all return the mobile SERP.")
    pages: Annotated[int, Field(ge=1, le=10)] | None = Field(None, description="Number of search results pages to scrape (1-10). Paid add-on: +2 credits per page after the first ([pricing](/guides/providers#google-search-multi-page-pricing)). Cannot be combined with 'url' — in that shape, depth comes from the URL's 'num' (rounded up to whole pages of 10, capped at 10 pages).")
    include: GoogleMonitorRequestInclude | None = Field(None, description='Optional flags for including additional response data')


class GoogleProductRequest(_Request):
    productResultToken: Annotated[str, Field(min_length=1, max_length=512)] = Field(..., description='The `productResultToken` from a Google Search shopping card, or from a Google AI Mode shopping card or inline product. The token carries the query, locale and location of the request that issued it, so the request takes no other field.')


class GoogleGotoRequest(_Request):
    url: str = Field(..., description='The Google redirect link to resolve, as an absolute URL. Must be a `google.com` or `www.google.com` link with a `/goto` or `/url` path — the form shipped as `redirectLink` beside every resolved link on Google Search, Google News, and AI Mode responses.')


class GoogleNewsMonitorRequestInclude(_Request):
    html: bool | None = Field(None, description='Include raw HTML response from Google News')


class GoogleNewsMonitorRequest(_Request):
    query: Annotated[str, Field(min_length=1, max_length=10000)] = Field(..., description='The search query to execute on Google News')
    country: CountryCode | None = Field(None, description='ISO 3166-1 alpha-2 country code for localized news results. See [List of countries](/api-reference/endpoint/countries) for the codes each provider supports.')
    gl: str | None = Field(None)
    hl: str | None = Field(None)
    device: Literal['desktop', 'mobile', 'ios', 'android'] | None = Field(None, description="Device the search is run from. 'desktop' returns the desktop news SERP; 'ios' (Safari on iPhone), 'android' (Chrome on Android) and 'mobile' (alias for 'android') all return the mobile news SERP.")
    pages: Annotated[int, Field(ge=1, le=10)] | None = Field(None, description='Number of news results pages to scrape (1-10). Paid add-on: +2 credits per page after the first ([pricing](/guides/providers#google-search-multi-page-pricing)).')
    include: GoogleNewsMonitorRequestInclude | None = Field(None, description='Optional flags for including additional response data')


class PerplexityMonitorRequestInclude(_Request):
    html: bool | None = Field(None, description='Include a URL to the full HTML of the response')
    markdown: bool | None = Field(None, description='Include markdown-formatted response in the result')
    rawResponse: bool | None = Field(None, description='Include raw streaming response events')


class PerplexityMonitorRequest(_Request):
    prompt: Annotated[str, Field(min_length=1, max_length=10000)] = Field(..., description='The prompt to send to Perplexity')
    country: CountryCode = Field(..., description='Country/region code for localized response, using ISO 3166-1 alpha-2 country codes.')
    include: PerplexityMonitorRequestInclude | None = Field(None, description='Optional flags for including additional response formats')
    state: StateCode | None = Field(None)


class AiModeMonitorRequestInclude(_Request):
    html: bool | None = Field(None, description='Include a URL to the full HTML of the response')
    markdown: bool | None = Field(None, description='Include markdown-formatted response in the result. `result.markdown` is returned only when this is `true`.')
    googleGoto: bool | None = Field(None, description='Ignored since 8th September 2026. Every redirect link now ships as `redirectLink` beside its destination, so both are returned without this flag. Requests still sending it behave as if it were absent.')


class AiModeMonitorRequest(_Request):
    prompt: Annotated[str, Field(min_length=1, max_length=10000)] = Field(..., description='The prompt to send to AI Mode')
    country: CountryCode | None = Field(None, description='Country/region code for localized response, using ISO 3166-1 alpha-2 country codes.')
    gl: str | None = Field(None)
    hl: str | None = Field(None)
    location: str | None = Field(None, description="Google canonical location name for geo-targeted results, in comma-separated format: 'City,Region,Country' (see https://developers.google.com/google-ads/api/reference/data/geotargets for all ~100,000 supported locations). Use alongside 'country' for city-level precision. Mutually exclusive with 'uule' — provide one or the other, not both. When both `location` and `uule` are omitted, cloro pins results to the country's canonical location (e.g. `Portugal` for `PT`) where it has one; otherwise Googl")
    uule: str | None = Field(None, description="Pre-encoded Google UULE string for precise geo-targeting. Use this when you have a pre-built UULE value instead of a location name. Mutually exclusive with 'location' — provide one or the other, not both.")
    device: Literal['desktop', 'mobile'] | None = Field(None, description='Device type for search results')
    include: AiModeMonitorRequestInclude | None = Field(None, description='Optional flags for including additional response formats')


class BingAiModeMonitorRequestInclude(_Request):
    html: bool | None = Field(None, description='Include a URL to the full HTML of the page that Bing rendered')
    markdown: bool | None = Field(None, description='Include the answer formatted in Markdown in the result. `result.markdown` is returned only when this is `true`.')


class BingAiModeMonitorRequest(_Request):
    prompt: Annotated[str, Field(min_length=1, max_length=3500)] = Field(..., description='The prompt to send to Bing AI Mode. Bing puts the prompt in the page URL, so the limit is 3,500 characters after URL encoding. A letter, digit or space counts as 1, most punctuation as 3, an accented or Cyrillic letter as 6, and a Chinese, Japanese or Korean character as 9. Thus a CJK prompt can have a maximum of 388 characters. A longer prompt returns a 400 error: "Prompt is too long (max 3,500 characters, fewer for non-Latin scripts)".')
    country: CountryCode = Field(..., description='Country/region code for localized response, using ISO 3166-1 alpha-2 country codes. Bing AI Mode accepts all countries except BY, CN, IR, RU, SY and VE. `GET /v1/countries?model=bing_aimode` returns the list.')
    state: StateCode | None = Field(None)
    include: BingAiModeMonitorRequestInclude | None = Field(None, description='Optional flags for including additional response formats')


class BatchTaskRequestWebhook(_Request):
    url: str = Field(..., description='URL to receive the webhook POST request when the task completes.')


class BatchTaskRequest(_Request):
    taskType: Literal['AIMODE', 'BING_AIMODE', 'GOOGLE', 'GOOGLE_NEWS', 'GOOGLE_PRODUCT', 'GEMINI', 'CHATGPT', 'PERPLEXITY'] = Field(..., description='The AI provider to use for this task.')
    payload: dict = Field(..., description="The provider's request body, validated against the same schema as its sync endpoint (for example `ChatGPTMonitorRequest`). That makes `country` required here too, or `gl` on the Google endpoints. For `GOOGLE_PRODUCT`, send only `productResultToken`.")
    priority: Annotated[int, Field(ge=1, le=10)] | None = Field(None, description='Task priority level (1-10). Higher numbers are processed first. Defaults to 1.')
    idempotencyKey: str | None = Field(None, description='Unique string to prevent duplicate task creation. Must be unique across your account.')
    webhook: BatchTaskRequestWebhook | None = Field(None, description='Webhook configuration for task completion notification.')

TASK_PAYLOADS = {
    "CHATGPT": ChatGPTMonitorRequest, "GEMINI": GeminiMonitorRequest,
    "GOOGLE": GoogleMonitorRequest, "GOOGLE_PRODUCT": GoogleProductRequest,
    "GOOGLE_NEWS": GoogleNewsMonitorRequest, "PERPLEXITY": PerplexityMonitorRequest,
    "AIMODE": AiModeMonitorRequest, "BING_AIMODE": BingAiModeMonitorRequest,
}


class AsyncTask(BatchTaskRequest):
    @model_validator(mode="after")
    def payload_shape(self):
        self.payload = TASK_PAYLOADS[self.taskType].model_validate(self.payload).model_dump(mode="json", exclude_none=True)
        return self

class MonitorChatgpt(ChatGPTMonitorRequest):
    """Monitor ChatGPT Responses."""
    operation: Literal['monitor_chatgpt'] = Field('monitor_chatgpt', title='Monitor ChatGPT Responses', json_schema_extra={"ui:hidden": True})

class MonitorGemini(GeminiMonitorRequest):
    """Monitor Gemini Responses."""
    operation: Literal['monitor_gemini'] = Field('monitor_gemini', title='Monitor Gemini Responses', json_schema_extra={"ui:hidden": True})

class MonitorGoogle(GoogleMonitorRequest):
    """Monitor Google Search Results."""
    operation: Literal['monitor_google'] = Field('monitor_google', title='Monitor Google Search Results', json_schema_extra={"ui:hidden": True})

class GetGoogleProduct(GoogleProductRequest):
    """Get a Google shopping card product."""
    operation: Literal['get_google_product'] = Field('get_google_product', title='Get a Google shopping card product', json_schema_extra={"ui:hidden": True})

class ResolveGoogleGoto(GoogleGotoRequest):
    """Resolve a Google redirect link."""
    operation: Literal['resolve_google_goto'] = Field('resolve_google_goto', title='Resolve a Google redirect link', json_schema_extra={"ui:hidden": True})

class MonitorGoogleNews(GoogleNewsMonitorRequest):
    """Monitor Google News Results."""
    operation: Literal['monitor_google_news'] = Field('monitor_google_news', title='Monitor Google News Results', json_schema_extra={"ui:hidden": True})

class MonitorPerplexity(PerplexityMonitorRequest):
    """Monitor Perplexity Responses."""
    operation: Literal['monitor_perplexity'] = Field('monitor_perplexity', title='Monitor Perplexity Responses', json_schema_extra={"ui:hidden": True})

class MonitorAiMode(AiModeMonitorRequest):
    """Monitor AI Mode Responses."""
    operation: Literal['monitor_ai_mode'] = Field('monitor_ai_mode', title='Monitor AI Mode Responses', json_schema_extra={"ui:hidden": True})

class MonitorBingAiMode(BingAiModeMonitorRequest):
    """Monitor Bing AI Mode Responses."""
    operation: Literal['monitor_bing_ai_mode'] = Field('monitor_bing_ai_mode', title='Monitor Bing AI Mode Responses', json_schema_extra={"ui:hidden": True})

class GetCountries(_Input):
    """List of countries."""
    operation: Literal['get_countries'] = Field('get_countries', title='List of countries', json_schema_extra={"ui:hidden": True})
    model: Literal['aimode', 'aioverview', 'bing_aimode', 'chatgpt', 'gemini', 'google', 'perplexity'] | None = Field(None, description='Filter countries available for a specific model. Omit to return all supported countries.')

class CreateAsyncTask(AsyncTask):
    """Create async task."""
    operation: Literal['create_async_task'] = Field('create_async_task', title='Create async task', json_schema_extra={"ui:hidden": True})

class CreateBatchAsyncTasks(_Input):
    """Create batch async tasks."""
    operation: Literal['create_batch_async_tasks'] = Field('create_batch_async_tasks', title='Create batch async tasks', json_schema_extra={"ui:hidden": True})
    tasks: list[AsyncTask] = Field(..., min_length=1, max_length=500, description="Up to 500 tasks. Each can succeed or fail independently; inspect the returned summary and results.")

class GetTaskStatus(_Input):
    """Get async task status."""
    operation: Literal['get_task_status'] = Field('get_task_status', title='Get async task status', json_schema_extra={"ui:hidden": True})
    taskId: UUID = Field(..., description='The ID of the task to fetch.')

class GetAsyncStatus(_Input):
    """Get async queue status."""
    operation: Literal['get_async_status'] = Field('get_async_status', title='Get async queue status', json_schema_extra={"ui:hidden": True})

class ClearAsyncQueue(_Input):
    """Clear queued async tasks."""
    operation: Literal['clear_async_queue'] = Field('clear_async_queue', title='Clear queued async tasks', json_schema_extra={"ui:hidden": True})
    # The API removes all queued tasks in the account; in-flight tasks continue.

class GetCredits(_Input):
    """Get credit balance."""
    operation: Literal['get_credits'] = Field('get_credits', title='Get credit balance', json_schema_extra={"ui:hidden": True})

class GetStates(_Input):
    """List of states."""
    operation: Literal['get_states'] = Field('get_states', title='List of states', json_schema_extra={"ui:hidden": True})
    country: Annotated[str, Field(min_length=2, max_length=2, pattern='^[A-Z]{2}$')] = Field(..., description='ISO 3166-1 alpha-2 country code. Only "US" returns results.')

CloroOperation = Annotated[Union[MonitorChatgpt, MonitorGemini, MonitorGoogle, GetGoogleProduct, ResolveGoogleGoto, MonitorGoogleNews, MonitorPerplexity, MonitorAiMode, MonitorBingAiMode, GetCountries, CreateAsyncTask, CreateBatchAsyncTasks, GetTaskStatus, GetAsyncStatus, ClearAsyncQueue, GetCredits, GetStates], Field(discriminator="operation")]


class CloroConfig(NodeConfig[CloroOperation, CloroCredential]):
    pass


ROUTES = {'monitor_chatgpt': ('POST', '/v1/monitor/chatgpt'), 'monitor_gemini': ('POST', '/v1/monitor/gemini'), 'monitor_google': ('POST', '/v1/monitor/google'), 'get_google_product': ('POST', '/v1/monitor/google/product'), 'resolve_google_goto': ('POST', '/v1/monitor/google/goto'), 'monitor_google_news': ('POST', '/v1/monitor/google/news'), 'monitor_perplexity': ('POST', '/v1/monitor/perplexity'), 'monitor_ai_mode': ('POST', '/v1/monitor/aimode'), 'monitor_bing_ai_mode': ('POST', '/v1/monitor/bing/aimode'), 'get_countries': ('GET', '/v1/countries'), 'create_async_task': ('POST', '/v1/async/task'), 'create_batch_async_tasks': ('POST', '/v1/async/task/batch'), 'get_task_status': ('GET', '/v1/async/task/{taskId}'), 'get_async_status': ('GET', '/v1/async/status'), 'clear_async_queue': ('DELETE', '/v1/async/queue'), 'get_credits': ('GET', '/v1/credits'), 'get_states': ('GET', '/v1/states')}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {str(k).replace(secret, "[redacted]"): _redact(v, secret) for k, v in value.items()}
    return value


class CloroNode(WorkflowNode):
    integration_type = "automation-cloro"
    credential_provider_labels = {"cloro": "Cloro Account"}
    connection_evidence = ConnectionEvidence(operation="get_credits", noun="Cloro account credit balance")

    @classmethod
    def get_config_model(cls):
        return CloroConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Cloro API key")
        secret = self.config.credentials.api_key
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "taskId" in values:
            path = path.replace("{taskId}", quote(values.pop("taskId"), safe=""))
        kwargs = {}
        if method == "GET":
            kwargs["params"] = values
        elif method == "POST":
            kwargs["json"] = values.pop("tasks") if config.operation == "create_batch_async_tasks" else values
        # No automatic retry: monitoring consumes credits and submission can create tasks.
        async with guarded_async_client(timeout=180, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Bearer " + secret, "Accept": "application/json"}, **kwargs)
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Cloro did not return JSON") from None
        if not response.is_success or isinstance(body, dict) and body.get("success") is False:
            error = body.get("error", {}) if isinstance(body, dict) else {}
            return {"status": "error", "status_code": response.status_code,
                "error": _redact(error.get("message", "Cloro request failed") if isinstance(error, dict) else str(error), secret),
                "provider_error": _redact(error, secret)}
        if not isinstance(body, (dict, list)):
            raise ValueError("Cloro returned an unexpected JSON shape")
        if config.operation == "get_credits" and (not isinstance(body, dict) or type(body.get("remaining")) is not int or not {"perCycle", "cycleResetsAt"} <= body.keys()):
            raise ValueError("Cloro returned an incomplete credit balance")
        # Preserve engine-specific results and batch per-task failures for downstream steps.
        return {"status": "success", "data": _redact(body, secret)}
