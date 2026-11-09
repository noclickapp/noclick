"""Olostep's documented scraping, research and scheduling API with pasted API keys.

Each operation makes one request to the pinned provider route. Async jobs and
paginated results stay explicit: callers poll IDs or pass returned cursors.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class OlostepAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Olostep API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.olostep.com/dashboard/",
            "x-credential-instructions": "Copy your API key from the Olostep dashboard and paste it here. NoClick sends it as a bearer token to api.olostep.com. The credit balance read checks access without spending credits.",
        })
    credential_type: Literal["olostep_api_key"] = Field("olostep_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def resource_ids(cls, value, info):
        if info.field_name in {"scrape_id", "batch_id", "crawl_id", "map_id", "answer_id", "search_id", "schedule_id"} and value is not None:
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
                raise ValueError("Use a single Olostep resource ID")
        return value

    @field_validator("metadata", mode="before", check_fields=False)
    @classmethod
    def metadata_values(cls, value, info):
        if info.field_name != "metadata" or value is None:
            return value
        if not isinstance(value, dict) or len(value) > 50:
            raise ValueError("Metadata takes at most 50 key-value pairs")
        result = {}
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 40 or any(c in key for c in "[]"):
                raise ValueError("Metadata keys take at most 40 characters without square brackets")
            if not isinstance(item, (str, int, float, bool)):
                raise ValueError("Metadata values must be strings, numbers or booleans")
            item = str(item).lower() if isinstance(item, bool) else str(item)
            if len(item) > 500:
                raise ValueError("Metadata values take at most 500 characters")
            result[key] = item
        return result


class OlostepCreateScrapeParser(_Input):
    id: str = Field(..., min_length=1, description='ID of the parser to use.')


class OlostepCreateScrapeLlmExtract(_Input):
    json_schema: dict[str, Any] | None = Field(None, alias="schema", description='JSON Schema for the extracted data. The top level must be an object schema, e.g. {"type": "object", "properties": {"title": {"type": "string"}}}.')


class OlostepCreateScrapeStorage(_Input):
    expires_in: Literal['10d', '30d', '60d', '90d', '180d', '365d', 'never'] = Field(..., description='How long to keep the scrape result. never retains it indefinitely. Required when storage is sent. Omit storage entirely for the default of about 7 days.')


class OlostepCreateScrapeConfig(_Input):
    'Initiate a web page scrape'
    operation: Literal["create_scrape"] = Field("create_scrape", json_schema_extra={"ui:hidden": True})
    url_to_scrape: str = Field(..., min_length=1, pattern=r"^https?://[^/\s]+", description='The URL to start scraping from.')
    formats: list[Literal['html', 'markdown', 'text', 'json', 'raw_pdf', 'screenshot']] | None = Field(None, description='Formats in which you want the content.')
    wait_before_scraping: int | None = Field(None, description='Time to wait in milliseconds before starting the scraping.')
    country: str | None = Field(None, min_length=1, description='Residential country to load the request from.\n\nSupported values are:\n- US (United States)\n- CA (Canada)\n- IT (Italy)\n- IN (India)\n- GB (England)\n- JP (Japan)\n- MX (Mexico)\n- AU (Australia)\n- ID (Indonesia)\n- UA (UAE)\n- RU (Russia)\n- RANDOM\n\nSome operations, like scraping Google Search and Google News, support all countries.')
    transformer: Literal['postlight', 'none'] | None = Field(None, description="Specify the HTML transformer to use, if any. Postlight's Mercury Parser library is used to remove ads and other unwanted content from the scraped content.")
    remove_images: bool | None = Field(None, description='Option to remove images from the scraped content. Defaults to false.')
    parser: OlostepCreateScrapeParser | None = Field(None, description='When defining json as a format, you can use this parameter to specify the parser to use. Parsers are useful to extract structured content from web pages. Olostep has a few parsers built in for most common web pages, and you can also create your own parsers.')
    llm_extract: OlostepCreateScrapeLlmExtract | None = Field(None)
    max_age: int | None = Field(None, ge=0, description='Maximum acceptable age of cached content, in seconds. When a matching scrape already exists and is newer than max_age seconds, Olostep returns the stored result instead of launching a new browser scrape. Defaults to 0 (always scrape fresh). In the dashboard playground, the default is 86400 (24 hours). The maximum allowed value is 604800 (7 days). See the Caching section in the Scrapes feature docs for details.')
    storage: OlostepCreateScrapeStorage | None = Field(None, description="Controls how long this scrape's result is retained. When omitted, results are kept for about 7 days. The result, hosted URLs, and GET /v1/scrapes/{scrape_id} stay available for the retention window. This is separate from max_age, which controls cache freshness. See the Storage section in the Scrapes feature docs for details.")


class OlostepGetScrapeConfig(_Input):
    'Retrieve scrape result'
    operation: Literal["get_scrape"] = Field("get_scrape", json_schema_extra={"ui:hidden": True})
    scrape_id: str = Field(..., min_length=1, max_length=256)


class OlostepListRecentBatchesConfig(_Input):
    'List recent batches'
    operation: Literal["list_recent_batches"] = Field("list_recent_batches", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, le=100)
    source: str | None = Field(None, min_length=1)


class OlostepCreateBatchItemsItem(_Input):
    custom_id: str = Field(..., min_length=1, description='An internal unique identifier for the url.')
    url: str = Field(..., min_length=1, pattern=r"^https?://[^/\s]+", description='URL of the item.')
    metadata: dict[str, str] | None = Field(None, description='Item-level metadata. Attach key-value pairs to individual items for tracking, filtering, or correlation with your internal systems.')


class OlostepCreateBatchParser(_Input):
    id: str = Field(..., min_length=1, description='Parser to be used for the batch.')


class OlostepCreateBatchConfig(_Input):
    'Start a new batch'
    operation: Literal["create_batch"] = Field("create_batch", json_schema_extra={"ui:hidden": True})
    items: list[OlostepCreateBatchItemsItem] = Field(..., description='Array of items to be processed in the batch.')
    country: str | None = Field(None, min_length=1, description='Country for the batch execution. Provide in ISO 3166-1 alpha-2 codes like US(USA), IN(India), etc')
    parser: OlostepCreateBatchParser | None = Field(None, description='You can use this parameter to specify the parser to use. Parsers are useful to extract structured content from web pages. Olostep has a few parsers built in for most common web pages, and you can also create your own parsers.')
    metadata: dict[str, str] | None = Field(None)
    webhook: str | None = Field(None, min_length=1, pattern=r"^https?://[^/\s]+", description='HTTPS URL to receive a POST request when the batch completes. Must be a publicly accessible URL using `http://` or `https://` protocol. Cannot point to localhost or private IP addresses. See [Webhooks](/api-reference/common/webhooks) for payload format and retry behavior.')


class OlostepGetBatchConfig(_Input):
    'Retrieve batch information'
    operation: Literal["get_batch"] = Field("get_batch", json_schema_extra={"ui:hidden": True})
    batch_id: str = Field(..., min_length=1, max_length=256)


class OlostepUpdateBatchMetadataConfig(_Input):
    'Update batch metadata'
    operation: Literal["update_batch_metadata"] = Field("update_batch_metadata", json_schema_extra={"ui:hidden": True})
    batch_id: str = Field(..., min_length=1, max_length=256)
    metadata: dict[str, str] = Field(...)


class OlostepListBatchItemsConfig(_Input):
    'Retrieve completed or failed items list optionally with content for a specific batch'
    operation: Literal["list_batch_items"] = Field("list_batch_items", json_schema_extra={"ui:hidden": True})
    batch_id: str = Field(..., min_length=1, max_length=256)
    status: Literal['completed', 'failed'] | None = Field(None)
    cursor: int | None = Field(None)
    limit: int | None = Field(None, ge=1, le=10000)


class OlostepCreateCrawlScrapeOptions(_Input):
    formats: list[Literal['html', 'markdown', 'text', 'json', 'screenshot']] | None = Field(None, description='Output formats to request for each scraped page. Defaults to `["html", "markdown"]` when omitted. `html` is always included automatically. `json` is automatically added when a `parser` is provided. Note: `raw_pdf` is not supported — PDFs cannot be crawled.')
    parser: str | None = Field(None, min_length=1, description='Parser name to run on each page and produce structured `json` output (e.g. `"@olostep/extract-emails"`). Automatically adds `json` to `formats` when set.')


class OlostepCreateCrawlStorage(_Input):
    expires_in: Literal['7d', '10d', '30d', '60d', '90d', '180d', '365d', 'never'] | None = Field(None, description='How long to keep the stored files. 7d is the default, never retains them indefinitely. Omitting expires_in inside storage also means 7d.')


class OlostepCreateCrawlConfig(_Input):
    'Start a new crawl'
    operation: Literal["create_crawl"] = Field("create_crawl", json_schema_extra={"ui:hidden": True})
    start_url: str = Field(..., min_length=1, description='The starting point of the crawl.')
    max_pages: float = Field(..., description='Maximum number of pages to crawl. Recommended for most use cases like crawling an entire website.')
    max_depth: float | None = Field(None, description='Maximum depth of the crawl. Useful to extract only up to n-degree of links.')
    include_urls: list[str] | None = Field(None, description='URL path patterns to include in the crawl using glob syntax.\n\nDefaults to `/**` which includes all URLs. Use patterns like `/blog/**` to crawl specific sections (e.g., only blog pages), `/products/*.html` for product pages, or multiple patterns for different sections. Supports standard glob features like * (any characters) and ** (recursive matching).')
    exclude_urls: list[str] | None = Field(None, description='URL path names in glob pattern to exclude. For example: `/careers/**`. Excluded URLs will supersede included URLs.')
    include_external: bool | None = Field(None, description='Crawl first-degree external links.')
    include_subdomain: bool | None = Field(None, description='Include subdomains of the website. `false` by default.')
    follow_robots_txt: bool | None = Field(None, description='Whether to respect robots.txt rules. If set to `false`, the crawler will scrape the website regardless of robots.txt disallow directives. `true` by default.')
    webhook: str | None = Field(None, min_length=1, pattern=r"^https?://[^/\s]+", description='HTTPS URL to receive a POST request when the crawl completes. Must be a publicly accessible URL using `http://` or `https://` protocol. Cannot point to localhost or private IP addresses. See [Webhooks](/api-reference/common/webhooks) for payload format and retry behavior.')
    scrape_options: OlostepCreateCrawlScrapeOptions | None = Field(None, description='Controls what each individual page scrape requests from the Olostep API. All fields are optional.')
    storage: OlostepCreateCrawlStorage | None = Field(None, description="Controls how long this crawl's stored files (its crawled pages) are retained. When omitted, they are kept for 7 days. The value in effect is returned in the response as storage.expires_in. See the Storage section in the feature docs. An invalid value returns 400 with code invalid_storage_expires_in.")


class OlostepGetCrawlConfig(_Input):
    'Retrieve crawl information'
    operation: Literal["get_crawl"] = Field("get_crawl", json_schema_extra={"ui:hidden": True})
    crawl_id: str = Field(..., min_length=1, max_length=256)


class OlostepListCrawlPagesConfig(_Input):
    'Retrieve list of crawled pages optionally with content'
    operation: Literal["list_crawl_pages"] = Field("list_crawl_pages", json_schema_extra={"ui:hidden": True})
    crawl_id: str = Field(..., min_length=1, max_length=256)
    cursor: int | None = Field(None)
    limit: int | None = Field(None)
    search_query: str | None = Field(None, min_length=1)
    formats: list[Literal['html', 'markdown']] | None = Field(None)


class OlostepCreateMapStorage(_Input):
    expires_in: Literal['7d', '10d', '30d', '60d', '90d', '180d', '365d', 'never'] | None = Field(None, description='How long to keep the stored files. 7d is the default, never retains them indefinitely. Omitting expires_in inside storage also means 7d.')


class OlostepCreateMapConfig(_Input):
    'Get all the urls on a certain website'
    operation: Literal["create_map"] = Field("create_map", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, pattern=r"^https?://[^/\s]+", description='The URL of the website for which you want the links')
    search_query: str | None = Field(None, min_length=1, description='An optional search query to sort the links by search relevance.')
    top_n: float | None = Field(None, description='An optional number to limit to only top n links for a search query.')
    include_subdomain: bool | None = Field(None, description='Include subdomains of the given URL. `true` by default.')
    include_urls: list[str] | None = Field(None, description='URL path patterns to include using glob syntax. For example: `/blog/**` to only include blog URLs. Only URLs matching these patterns will be returned.')
    exclude_urls: list[str] | None = Field(None, description='URL path patterns to exclude using glob syntax. For example: `/careers/**`. Excluded URLs will supersede included URLs.')
    cursor: str | None = Field(None, min_length=1, description='OPTIONAL: Pagination cursor from a previous response. When provided, returns the next set of URLs from where the previous request left off due to response size limit.')
    storage: OlostepCreateMapStorage | None = Field(None, description="Controls how long this map's stored files (its result and the pages scraped during discovery) are retained. When omitted, they are kept for 7 days. The value in effect is returned in the response as storage.expires_in. See the Storage section in the feature docs. An invalid value returns 400 with code invalid_storage_expires_in.")


class OlostepGetMapConfig(_Input):
    'Get Map'
    operation: Literal["get_map"] = Field("get_map", json_schema_extra={"ui:hidden": True})
    map_id: str = Field(..., min_length=1, max_length=256)


class OlostepCreateAnswerStorage(_Input):
    expires_in: Literal['7d', '10d', '30d', '60d', '90d', '180d', '365d', 'never'] | None = Field(None, description='How long to keep the stored files. 7d is the default, never retains them indefinitely. Omitting expires_in inside storage also means 7d.')


class OlostepCreateAnswerConfig(_Input):
    'Create Answer'
    operation: Literal["create_answer"] = Field("create_answer", json_schema_extra={"ui:hidden": True})
    task: str = Field(..., min_length=1, description='The task to be performed.')
    json_format: dict[str, Any] | None = Field(None, description='The desired output JSON object with empty values as a schema, or simply describe the data you want as a string.')
    storage: OlostepCreateAnswerStorage | None = Field(None, description="Controls how long this answer's stored files (its result file and the pages fetched to build it) are retained. When omitted, they are kept for 7 days. The value in effect is returned in the response as storage.expires_in. See the Storage section in the feature docs. An invalid value returns 400 with code invalid_storage_expires_in.")


class OlostepGetAnswerConfig(_Input):
    'Get Answer'
    operation: Literal["get_answer"] = Field("get_answer", json_schema_extra={"ui:hidden": True})
    answer_id: str = Field(..., min_length=1, max_length=256)


class OlostepCreateSearchScrapeOptions(_Input):
    formats: list[Literal['html', 'markdown']] | None = Field(None, description="Output formats to request for each scraped page. Defaults to ['markdown'] when omitted. For now only 'html' and 'markdown' are supported on /v1/searches.")
    remove_css_selectors: str | None = Field(None, min_length=1, description="Option to remove certain CSS selectors from the content. Forwarded to /v1/scrapes. Defaults to 'default' which strips ['nav','footer','script','style','noscript','svg',[role=alert],[role=banner],[role=dialog],[role=alertdialog],[role=region][aria-label*=skip i],[aria-modal=true]]. Pass 'none' to disable, or a JSON-stringified array of selectors to remove.")
    timeout: int | None = Field(None, ge=1, le=60, description="Wallclock budget in seconds for the entire scrape phase. After this elapses, the search returns with whatever links are available — content fields will be null for any links that hadn't finished scraping.")


class OlostepCreateSearchStorage(_Input):
    expires_in: Literal['7d', '10d', '30d', '60d', '90d', '180d', '365d', 'never'] | None = Field(None, description='How long to keep the stored files. 7d is the default, never retains them indefinitely. Omitting expires_in inside storage also means 7d.')


class OlostepCreateSearchConfig(_Input):
    'Create Search'
    operation: Literal["create_search"] = Field("create_search", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, description='The search query in natural language.')
    limit: int | None = Field(None, ge=1, le=25, description='Maximum number of links to return after deduplication.')
    include_domains: list[str] | None = Field(None, description='Restrict results to these domains. Bare hosts only — leading `http(s)://` and trailing slashes are stripped automatically.')
    exclude_domains: list[str] | None = Field(None, description='Exclude results from these domains. Bare hosts only — leading `http(s)://` and trailing slashes are stripped automatically.')
    fast_mode: bool | None = Field(None, description='Request a direct, low-latency search using your query verbatim. Default mode performs a broader search pass for wider result coverage.')
    scrape_options: OlostepCreateSearchScrapeOptions | None = Field(None)
    storage: OlostepCreateSearchStorage | None = Field(None, description="Controls how long this search's stored files (its file and any scraped link content) are retained. When omitted, they are kept for 7 days. The value in effect is returned in the response as storage.expires_in. See the Storage section in the feature docs. An invalid value returns 400 with code invalid_storage_expires_in.")


class OlostepGetSearchConfig(_Input):
    'Get Search'
    operation: Literal["get_search"] = Field("get_search", json_schema_extra={"ui:hidden": True})
    search_id: str = Field(..., min_length=1, max_length=256)


class OlostepCreateScheduleConfig(_Input):
    'Create Schedule'
    operation: Literal["create_schedule"] = Field("create_schedule", json_schema_extra={"ui:hidden": True})
    method: Literal['GET', 'POST'] = Field(..., description='HTTP method for the scheduled API call. Must be either GET or POST.')
    endpoint: str = Field(..., min_length=1, description="The endpoint URL to call when the schedule executes. For POST requests with Olostep endpoints, you can use short form (e.g., 'v1/scrapes', 'v1/batches', 'v1/crawls', 'v1/maps', 'v1/answers') which will be automatically prefixed with 'https://api.olostep.com/'. For other endpoints, provide the full URL.")
    payload: dict[str, Any] | None = Field(None, description='The payload to send with the API call. Can contain any JSON structure you need. For GET requests, this is typically empty. For POST requests, this should contain the data you want to send to the endpoint.')
    cron_expression: str | None = Field(None, min_length=1, description='Cron expression in 6 fields format (minute hour day month day-of-week year) for recurring schedules. Required for recurring schedules. Mutually exclusive with execute_at and text.')
    execute_at: str | None = Field(None, min_length=1, description='ISO 8601 datetime string for one-time schedule execution. Must be a valid future datetime. Required for one-time schedules. Mutually exclusive with cron_expression.')
    expression_timezone: str | None = Field(None, min_length=1, description="IANA timezone identifier (e.g., 'UTC', 'America/New_York', 'Europe/London') for the schedule. Required for recurring schedules, optional for one-time schedules. When using natural language text, this defaults to 'UTC'.")
    text: str | None = Field(None, min_length=1, description="Natural language text to automatically generate a cron expression. The system will convert your text into a valid cron expression. Examples: 'every 3 minutes', 'every day at 10am', 'every Monday at 9am'. Mutually exclusive with cron_expression and execute_at. When used, expression_timezone defaults to 'UTC'.")

    @model_validator(mode="after")
    def schedule_timing(self):
        if sum(bool(x) for x in (self.cron_expression, self.execute_at, self.text)) != 1:
            raise ValueError("Choose one of cron expression, execution time or natural language schedule")
        if self.execute_at:
            datetime.fromisoformat(self.execute_at.replace("Z", "+00:00"))
        return self


class OlostepListSchedulesConfig(_Input):
    'List Schedules'
    operation: Literal["list_schedules"] = Field("list_schedules", json_schema_extra={"ui:hidden": True})
    include_deleted: Literal['true', 'false'] | None = Field(None)


class OlostepGetScheduleConfig(_Input):
    'Get Schedule'
    operation: Literal["get_schedule"] = Field("get_schedule", json_schema_extra={"ui:hidden": True})
    schedule_id: str = Field(..., pattern='^schedule_', min_length=1, max_length=256)


class OlostepDeleteScheduleConfig(_Input):
    'Delete Schedule'
    operation: Literal["delete_schedule"] = Field("delete_schedule", json_schema_extra={"ui:hidden": True})
    schedule_id: str = Field(..., pattern='^schedule_', min_length=1, max_length=256)


class OlostepGetCreditInfoConfig(_Input):
    'Get credit info'
    operation: Literal["get_credit_info"] = Field("get_credit_info", json_schema_extra={"ui:hidden": True})


OlostepConfig = Annotated[Union[OlostepCreateScrapeConfig, OlostepGetScrapeConfig, OlostepListRecentBatchesConfig, OlostepCreateBatchConfig, OlostepGetBatchConfig, OlostepUpdateBatchMetadataConfig, OlostepListBatchItemsConfig, OlostepCreateCrawlConfig, OlostepGetCrawlConfig, OlostepListCrawlPagesConfig, OlostepCreateMapConfig, OlostepGetMapConfig, OlostepCreateAnswerConfig, OlostepGetAnswerConfig, OlostepCreateSearchConfig, OlostepGetSearchConfig, OlostepCreateScheduleConfig, OlostepListSchedulesConfig, OlostepGetScheduleConfig, OlostepDeleteScheduleConfig, OlostepGetCreditInfoConfig], Field(discriminator="operation")]


class OlostepFullConfig(NodeConfig[OlostepConfig, OlostepAPIKeyCredential]):
    pass


ROUTES = {'create_scrape': ('POST', '/v1/scrapes'), 'get_scrape': ('GET', '/v1/scrapes/{scrape_id}'), 'list_recent_batches': ('GET', '/v1/batches/recent'), 'create_batch': ('POST', '/v1/batches'), 'get_batch': ('GET', '/v1/batches/{batch_id}'), 'update_batch_metadata': ('PATCH', '/v1/batches/{batch_id}'), 'list_batch_items': ('GET', '/v1/batches/{batch_id}/items'), 'create_crawl': ('POST', '/v1/crawls'), 'get_crawl': ('GET', '/v1/crawls/{crawl_id}'), 'list_crawl_pages': ('GET', '/v1/crawls/{crawl_id}/pages'), 'create_map': ('POST', '/v1/maps'), 'get_map': ('GET', '/v1/maps/{map_id}'), 'create_answer': ('POST', '/v1/answers'), 'get_answer': ('GET', '/v1/answers/{answer_id}'), 'create_search': ('POST', '/v1/searches'), 'get_search': ('GET', '/v1/searches/{search_id}'), 'create_schedule': ('POST', '/v1/schedules'), 'list_schedules': ('GET', '/v1/schedules'), 'get_schedule': ('GET', '/v1/schedules/{schedule_id}'), 'delete_schedule': ('DELETE', '/v1/schedules/{schedule_id}'), 'get_credit_info': ('GET', '/user/credits/info')}
QUERY_FIELDS = {'create_scrape': [], 'get_scrape': [], 'list_recent_batches': ['limit', 'source'], 'create_batch': [], 'get_batch': [], 'update_batch_metadata': [], 'list_batch_items': ['status', 'cursor', 'limit'], 'create_crawl': [], 'get_crawl': [], 'list_crawl_pages': ['cursor', 'limit', 'search_query', 'formats'], 'create_map': [], 'get_map': [], 'create_answer': [], 'get_answer': [], 'create_search': [], 'get_search': [], 'create_schedule': [], 'list_schedules': ['include_deleted'], 'get_schedule': [], 'delete_schedule': [], 'get_credit_info': []}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    return value


class OlostepNode(WorkflowNode):
    integration_type = "automation-olostep"
    connection_evidence = ConnectionEvidence(noun="Olostep credit balance", operation="get_credit_info", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return OlostepFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Olostep API key")
        config = self.config.config
        secret = self.config.credentials.api_key
        method, path = ROUTES[config.operation]
        values = config.model_dump(by_alias=True, exclude_none=True, exclude={"operation"})
        for name in re.findall(r"{([^}]+)}", path):
            path = path.replace("{" + name + "}", quote(values.pop(name), safe=""))
        params = {name: values.pop(name) for name in QUERY_FIELDS[config.operation] if name in values}
        params = {k: ("true" if v else "false") if isinstance(v, bool) else v for k, v in params.items()}
        try:
            async with guarded_async_client(timeout=120, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://api.olostep.com" + path,
                    headers={"Authorization": "Bearer " + secret, "Accept": "application/json"},
                    params=params, **({"json": values} if method in {"POST", "PATCH"} else {}))
        except httpx.TransportError:
            # Never replay a job submission after an uncertain transport outcome.
            raise ValueError("Olostep request did not complete; inspect the dashboard before retrying a write") from None
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Olostep returned an unreadable response") from None
        if not isinstance(data, dict):
            raise ValueError("Expected an Olostep JSON object")
        if not response.is_success or data.get("object") == "error" or data.get("error"):
            return _redact({"status": "error", "http_status": response.status_code,
                "error": data.get("error") or data.get("detail") or data.get("message") or "Olostep request failed"}, secret)
        # Keep the provider envelope intact, including job status and pagination.
        return {"status": "success", "data": _redact(data, secret)}
