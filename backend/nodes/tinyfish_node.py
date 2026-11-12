"""Tinyfish REST API v1: browser automation, research, extraction and monitoring.

Contract: https://agent.tinyfish.ai/v1/openapi/{main,datasets,monitor,fetch,search,research}
Authentication: https://docs.tinyfish.ai/authentication
Each operation makes one request; list responses retain the provider's pagination.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from uuid import UUID
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class TinyfishAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Tinyfish API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://agent.tinyfish.ai/api-keys",
            "x-credential-instructions": "Create an API key on Tinyfish's API Keys page and paste it here. NoClick sends it in the X-API-Key header. Listing your runs verifies access; creating runs and populating datasets can use your Tinyfish wallet balance.",
        })
    credential_type: Literal["tinyfish_api_key"] = Field("tinyfish_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or any(ord(c) > 126 or ord(c) < 33 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def editor_metadata(cls, value):
        # Saved canvas configs carry credential attachment metadata beside fields.
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k != "credentialIds"}
        return value

    @field_validator("*", mode="after")
    @classmethod
    def valid_url_or_identifier(cls, value, info):
        if value is None:
            return value
        if info.field_name in {"id", "profile_id", "research_run_id"}:
            if not str(value) or str(value) in {".", ".."} or any(c in str(value) for c in "/?#\\") or any(ord(c) < 33 for c in str(value)):
                raise ValueError("Use a single Tinyfish resource ID")
        if info.field_name in {"url", "webhook_url", "urls"}:
            for url in value if isinstance(value, list) else [value]:
                parsed = urlsplit(url)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError("Use an HTTP or HTTPS URL without embedded credentials")
                if info.field_name == "webhook_url" and parsed.scheme != "https":
                    raise ValueError("Webhooks require HTTPS")
        return value

class TinyfishRunAgentConfig(_Input):
    mode: Literal['default', 'strict'] | None = Field(None, description='Agent behavior mode. "strict" enables fail-fast for test automation.')
    cursor_style: Literal['fish', 'standard', 'green-pointer'] | None = Field(None, description='Cursor style for the browser agent.')
    max_steps: int | None = Field(None, ge=1, le=500, description='Maximum tool-call steps before the agent stops. Defaults to 150.')
    max_duration_seconds: int | None = Field(None, ge=1, description='Maximum wall-clock seconds before the agent stops. Defaults to no limit.')


class TinyfishRunConfig(_Input):
    """Run browser automation synchronously."""
    operation: Literal["run"] = Field("run", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., description='Target website URL to automate', json_schema_extra={'format': 'uri'})
    goal: str = Field(..., min_length=1, description='Natural language description of what to accomplish on the website')
    browser_profile: Literal['lite', 'stealth'] | None = Field(None, description='Browser profile for execution. LITE uses standard browser, STEALTH uses anti-detection browser.')
    agent_config: TinyfishRunAgentConfig | None = Field(None, description='Agent behavior configuration')
    webhook_url: str | None = Field(None, description='HTTPS URL to receive webhook notifications for run lifecycle events. Must use HTTPS.', json_schema_extra={'format': 'uri'})
    use_profile: bool | None = Field(None, description='Opt-in to the default Browser Context Profile if Browser Context Profiles are enabled; legacy callers are silently ignored when the profiles feature is disabled. Returns 400 when enabled but no default profile is set.')
    profile_id: str | None = Field(None, min_length=1, description='Browser Context Profile ID to use when use_profile is true.')
    output_schema: dict[str, Any] | None = Field(None, description='Optional provider-supported structured-output schema subset for the run result. Unsupported fields are rejected before the request is accepted.')


class TinyfishStartRunAgentConfig(_Input):
    mode: Literal['default', 'strict'] | None = Field(None, description='Agent behavior mode. "strict" enables fail-fast for test automation.')
    cursor_style: Literal['fish', 'standard', 'green-pointer'] | None = Field(None, description='Cursor style for the browser agent.')
    max_steps: int | None = Field(None, ge=1, le=500, description='Maximum tool-call steps before the agent stops. Defaults to 150.')
    max_duration_seconds: int | None = Field(None, ge=1, description='Maximum wall-clock seconds before the agent stops. Defaults to no limit.')


class TinyfishStartRunConfig(_Input):
    """Start automation asynchronously."""
    operation: Literal["start_run"] = Field("start_run", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., description='Target website URL to automate', json_schema_extra={'format': 'uri'})
    goal: str = Field(..., min_length=1, description='Natural language description of what to accomplish on the website')
    browser_profile: Literal['lite', 'stealth'] | None = Field(None, description='Browser profile for execution. LITE uses standard browser, STEALTH uses anti-detection browser.')
    agent_config: TinyfishStartRunAgentConfig | None = Field(None, description='Agent behavior configuration')
    webhook_url: str | None = Field(None, description='HTTPS URL to receive webhook notifications for run lifecycle events. Must use HTTPS.', json_schema_extra={'format': 'uri'})
    use_profile: bool | None = Field(None, description='Opt-in to the default Browser Context Profile if Browser Context Profiles are enabled; legacy callers are silently ignored when the profiles feature is disabled. Returns 400 when enabled but no default profile is set.')
    profile_id: str | None = Field(None, min_length=1, description='Browser Context Profile ID to use when use_profile is true.')
    output_schema: dict[str, Any] | None = Field(None, description='Optional provider-supported structured-output schema subset for the run result. Unsupported fields are rejected before the request is accepted.')


class TinyfishListRunsConfig(_Input):
    """List and search runs."""
    operation: Literal["list_runs"] = Field("list_runs", json_schema_extra={"ui:hidden": True})
    status: Literal['PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED'] | None = Field(None, description='Filter by run status')
    goal: str | None = Field(None, max_length=500, description='Filter runs by goal text (case-insensitive partial match)')
    created_after: str | None = Field(None, description='Filter runs created after this ISO 8601 timestamp', json_schema_extra={'format': 'date-time'})
    created_before: str | None = Field(None, description='Filter runs created before this ISO 8601 timestamp', json_schema_extra={'format': 'date-time'})
    sort_direction: Literal['asc', 'desc'] | None = Field(None, description='Sort order by created_at')
    cursor: str | None = Field(None, description='Cursor for pagination (from previous response)')
    limit: int | None = Field(None, ge=1, le=100, description='Maximum number of results to return (1-100)')
    owner: Literal['me', 'team'] | None = Field(None, description="Whose records: me (default for a personal key) or team, made by the team's workflow keys (the only choice for a workflow key)")


class TinyfishGetRunConfig(_Input):
    """Get run by ID."""
    operation: Literal["get_run"] = Field("get_run", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Run ID')
    screenshots: Literal['url', 'none'] | None = Field(None, description='Screenshot delivery mode. url: absolute URLs to screenshot images. none: omit screenshots. Defaults to url.')
    html: Literal['url', 'none'] | None = Field(None, description='HTML snapshot delivery mode. url: absolute URLs to HTML snapshot pages (only non-null when capture_config.html was enabled). none: omit HTML URLs. Defaults to url.')


class TinyfishCancelRunConfig(_Input):
    """Cancel run by ID."""
    operation: Literal["cancel_run"] = Field("cancel_run", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Run ID')


class TinyfishListProfilesConfig(_Input):
    """List Browser Context Profiles."""
    operation: Literal["list_profiles"] = Field("list_profiles", json_schema_extra={"ui:hidden": True})


class TinyfishCreateProfileConfig(_Input):
    """Create a Browser Context Profile."""
    operation: Literal["create_profile"] = Field("create_profile", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=100)
    set_as_default: bool | None = Field(None)
    proxy_country_code: str | None = Field(None)


class TinyfishGetProfileConfig(_Input):
    """Get a Browser Context Profile."""
    operation: Literal["get_profile"] = Field("get_profile", json_schema_extra={"ui:hidden": True})
    profile_id: str = Field(..., min_length=1, description='Browser Context Profile ID')


class TinyfishUpdateProfileConfig(_Input):
    """Update a Browser Context Profile."""
    operation: Literal["update_profile"] = Field("update_profile", json_schema_extra={"ui:hidden": True})
    profile_id: str = Field(..., min_length=1, description='Browser Context Profile ID')
    name: str | None = Field(None, min_length=1, max_length=100)
    set_as_default: bool | None = Field(None)
    proxy_country_code: str | None = Field(None)

    @model_validator(mode="after")
    def has_update(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "profile_id"}):
            raise ValueError("Provide profile metadata to update")
        return self


class TinyfishDeleteProfileConfig(_Input):
    """Delete a Browser Context Profile."""
    operation: Literal["delete_profile"] = Field("delete_profile", json_schema_extra={"ui:hidden": True})
    profile_id: str = Field(..., min_length=1, description='Browser Context Profile ID')


class TinyfishCreateDatasetConfig(_Input):
    """Create a dataset."""
    operation: Literal["create_dataset"] = Field("create_dataset", json_schema_extra={"ui:hidden": True})
    prompt: str = Field(..., min_length=3, max_length=15000, description='What the dataset should contain, in plain English')
    target_rows: int | None = Field(None, ge=1, le=250, description='Rows to fill the dataset to, 1 to 250')
    populate: bool | None = Field(None, description='Start filling the dataset right away')


class TinyfishListDatasetsConfig(_Input):
    """List datasets."""
    operation: Literal["list_datasets"] = Field("list_datasets", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=100)
    cursor: str | None = Field(None, description="The previous page's next_cursor")


class TinyfishGetDatasetConfig(_Input):
    """Get a dataset."""
    operation: Literal["get_dataset"] = Field("get_dataset", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., description='Dataset ID')


class TinyfishGetDatasetRowsConfig(_Input):
    """Get rows."""
    operation: Literal["get_dataset_rows"] = Field("get_dataset_rows", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., description='Dataset ID')
    limit: int | None = Field(None, ge=1, le=2000)
    after: str | None = Field(None, max_length=32, description="The previous page's next_cursor")


class TinyfishPopulateDatasetConfig(_Input):
    """Populate a dataset."""
    operation: Literal["populate_dataset"] = Field("populate_dataset", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., description='Dataset ID')
    reset: bool | None = Field(None, description='Empty the dataset before filling it')
    target_rows: int | None = Field(None, ge=1, le=250, description='Rows to fill the dataset to, 1 to 250')


class TinyfishDeleteDatasetConfig(_Input):
    """Delete a dataset."""
    operation: Literal["delete_dataset"] = Field("delete_dataset", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., description='Dataset ID')


class TinyfishCreateMonitorConfig(_Input):
    """Create a Monitor."""
    operation: Literal["create_monitor"] = Field("create_monitor", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, max_length=100, description='Optional name for this Monitor.')
    schedule_cron: str = Field(..., max_length=100, description='Five-field cron expression, evaluated in UTC by default. Prefix with `CRON_TZ=<IANA zone>` (e.g. `CRON_TZ=America/New_York 0 9 * * 1-5`) to run in a timezone.')
    webhook_url: str | None = Field(None, description="Optional URL that receives each scheduled run's results.", json_schema_extra={'format': 'uri'})
    purpose: str | None = Field(None, min_length=1, max_length=2000, description='Optional plain-language description of the change that matters, e.g. "the price drops".')
    url: str = Field(..., description='Public webpage URL to monitor', json_schema_extra={'format': 'uri'})


class TinyfishListMonitorsConfig(_Input):
    """List Monitors."""
    operation: Literal["list_monitors"] = Field("list_monitors", json_schema_extra={"ui:hidden": True})


class TinyfishGetMonitorConfig(_Input):
    """Get a Monitor."""
    operation: Literal["get_monitor"] = Field("get_monitor", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=36, description='Monitor ID')


class TinyfishUpdateMonitorConfig(_Input):
    """Update a Monitor."""
    operation: Literal["update_monitor"] = Field("update_monitor", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=36, description='Monitor ID')
    status: Literal['active', 'paused'] | None = Field(None)
    schedule_cron: str | None = Field(None, max_length=100)
    name: str | None = Field(None, min_length=1, max_length=100)
    webhook_url: str | None = Field(None, json_schema_extra={'format': 'uri'})
    purpose: str | None = Field(None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def one_update_kind(self):
        updates = self.model_dump(exclude_none=True, exclude={"operation", "id"})
        if not updates or ("status" in updates and len(updates) != 1):
            raise ValueError("Change either status or monitor metadata in one request")
        return self


class TinyfishDeleteMonitorConfig(_Input):
    """Delete a Monitor."""
    operation: Literal["delete_monitor"] = Field("delete_monitor", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=36, description='Monitor ID')


class TinyfishSearchConfig(_Input):
    """Search the web."""
    operation: Literal["search"] = Field("search", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=2000, description='Search query')
    purpose: str | None = Field(None, min_length=1, max_length=2000, description='Why this search is being run — the underlying goal or task the results will be used for. Used to better rank results against your intent.')
    location: str | None = Field(None, description='Country code for geo-targeted results')
    language: str | None = Field(None, description='Language code for result language')
    include_domains: str | None = Field(None, description='Comma-separated list of domains to restrict results to')
    exclude_domains: str | None = Field(None, description='Comma-separated list of domains to exclude from results')
    domain_type: Literal['web', 'news', 'research_paper'] | None = Field(None, description='Type of search to perform: "web" for standard results, "news" for news articles, "research_paper" for academic papers. Defaults to "web".')
    after_date: str | None = Field(None, description='Return results after this date (YYYY-MM-DD)')
    before_date: str | None = Field(None, description='Return results before this date (YYYY-MM-DD)')
    recency_minutes: int | None = Field(None, ge=1, le=5256000, description='Return results from the past N minutes (1 to 5,256,000).')
    pub_year_min: int | None = Field(None, ge=0, le=9999, description='Return research papers published on or after this year (0-9999, inclusive). Only supported for domain_type=research_paper.')
    pub_year_max: int | None = Field(None, ge=0, le=9999, description='Return research papers published on or before this year (0-9999, inclusive). Only supported for domain_type=research_paper.')
    page: int | None = Field(None, ge=0, le=10, description='Page number for pagination, starting from 0 (max 10)')
    include_thumbnail: Literal['true', 'false'] | None = Field(None, description='When "true", each result includes a thumbnail_url when available. Defaults to false.')
    fetch: str | None = Field(None, max_length=256, description='JSON-encoded fetch configuration object.')


class TinyfishFetchUrlsConfig(_Input):
    """Fetch and extract content from URLs."""
    operation: Literal["fetch_urls"] = Field("fetch_urls", json_schema_extra={"ui:hidden": True})
    urls: list[str] = Field(..., min_length=1, max_length=10, description='Array of URLs to fetch (1-10). All URLs are fetched in parallel. Each URL is processed independently — if one fails, others still return successfully. Errors are reported per-URL in the errors array.')
    purpose: str | None = Field(None, min_length=1, max_length=2000, description='Why these URLs are being fetched — the underlying goal or task the content will be used for. Used to better tailor fetching and extraction to your intent.')
    format: Literal['markdown', 'html', 'json'] | None = Field(None, description='Output format for extracted content. "markdown" (default) is ideal for LLM consumption. "html" returns cleaned semantic HTML. "json" returns a structured document tree.')
    links: bool | None = Field(None, description='Extract all outbound links (<a href>) from each page. Useful for discovering related pages or navigating to specific content. Links are returned as absolute URLs in the links array of each result.')
    image_links: bool | None = Field(None, description='Extract all image URLs (<img src>) from each page. Useful for finding visual content or media assets. Image links are returned as absolute URLs in the image_links array of each result.')
    page_metadata: bool | None = Field(None, description='Return page-head metadata for each page in the page_metadata object of each result: canonical URL, favicon, robots directive, generator, viewport, keywords, all Open Graph (og), Twitter card (twitter), and article tags, and remaining named meta tags under `other`. Useful for SEO/technical audits and link-preview generation.')
    ttl: int | None = Field(None, ge=0, description="Caller freshness tolerance in seconds for the cached entry. Omit (default) for unlimited tolerance — any cached entry is acceptable. Set to 0 to prefer a live fetch; a cached entry is still served if the origin's Cache-Control: max-age covers its age, or the host is in the small allowlist of operator-pinned never-expire domains. Set to N > 0 to accept a cached entry whose age is below N; the upstream Cache-Control: max-age and the never-expire allowlist may extend (never shorten) this tolerance.")
    per_url_timeout_ms: int | None = Field(None, ge=1, le=110000, description='Wall-clock timeout budget in milliseconds applied independently to each URL. If one URL exceeds this budget, it returns a per-URL timeout error while other URLs in the same request continue.')


class TinyfishStartResearchConfig(_Input):
    """Start research asynchronously."""
    operation: Literal["start_research"] = Field("start_research", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=10000, description='Research question')
    mode: Literal['deep', 'max'] | None = Field(None, description='Depth of research. Omitted selects deep.')
    output_language: str | None = Field(None, description='BCP 47 language tag for the report')


class TinyfishGetResearchConfig(_Input):
    """Get research run by ID."""
    operation: Literal["get_research"] = Field("get_research", json_schema_extra={"ui:hidden": True})
    research_run_id: str = Field(..., description='Research run identifier')


# TinyFish's own MCP server: agents get its tools through a person's TinyFish sign-in.
TinyfishMcpCredential = mcp_credential("tinyfish", "https://agent.tinyfish.ai/mcp", app="TinyFish")
TinyfishCredential = Union[TinyfishAPIKeyCredential, TinyfishMcpCredential]


TinyfishConfig = Annotated[Union[
    TinyfishRunConfig,
    TinyfishStartRunConfig,
    TinyfishListRunsConfig,
    TinyfishGetRunConfig,
    TinyfishCancelRunConfig,
    TinyfishListProfilesConfig,
    TinyfishCreateProfileConfig,
    TinyfishGetProfileConfig,
    TinyfishUpdateProfileConfig,
    TinyfishDeleteProfileConfig,
    TinyfishCreateDatasetConfig,
    TinyfishListDatasetsConfig,
    TinyfishGetDatasetConfig,
    TinyfishGetDatasetRowsConfig,
    TinyfishPopulateDatasetConfig,
    TinyfishDeleteDatasetConfig,
    TinyfishCreateMonitorConfig,
    TinyfishListMonitorsConfig,
    TinyfishGetMonitorConfig,
    TinyfishUpdateMonitorConfig,
    TinyfishDeleteMonitorConfig,
    TinyfishSearchConfig,
    TinyfishFetchUrlsConfig,
    TinyfishStartResearchConfig,
    TinyfishGetResearchConfig
], Field(discriminator="operation")]


class TinyfishFullConfig(NodeConfig[TinyfishConfig, TinyfishCredential]):
    pass


# (method, fixed origin, contract path, parameter bindings, JSON body)
ROUTES = {'run': ('POST', 'https://agent.tinyfish.ai', '/v1/automation/run', {}, True),
 'start_run': ('POST', 'https://agent.tinyfish.ai', '/v1/automation/run-async', {}, True),
 'list_runs': ('GET',
               'https://agent.tinyfish.ai',
               '/v1/runs',
               {'status': ('query', 'status'),
                'goal': ('query', 'goal'),
                'created_after': ('query', 'created_after'),
                'created_before': ('query', 'created_before'),
                'sort_direction': ('query', 'sort_direction'),
                'cursor': ('query', 'cursor'),
                'limit': ('query', 'limit'),
                'owner': ('query', 'owner')},
               False),
 'get_run': ('GET',
             'https://agent.tinyfish.ai',
             '/v1/runs/{id}',
             {'id': ('path', 'id'), 'screenshots': ('query', 'screenshots'), 'html': ('query', 'html')},
             False),
 'cancel_run': ('POST', 'https://agent.tinyfish.ai', '/v1/runs/{id}/cancel', {'id': ('path', 'id')}, False),
 'list_profiles': ('GET', 'https://agent.tinyfish.ai', '/v1/profiles', {}, False),
 'create_profile': ('POST', 'https://agent.tinyfish.ai', '/v1/profiles', {}, True),
 'get_profile': ('GET',
                 'https://agent.tinyfish.ai',
                 '/v1/profiles/{profileId}',
                 {'profile_id': ('path', 'profileId')},
                 False),
 'update_profile': ('PATCH',
                    'https://agent.tinyfish.ai',
                    '/v1/profiles/{profileId}',
                    {'profile_id': ('path', 'profileId')},
                    True),
 'delete_profile': ('DELETE',
                    'https://agent.tinyfish.ai',
                    '/v1/profiles/{profileId}',
                    {'profile_id': ('path', 'profileId')},
                    False),
 'create_dataset': ('POST', 'https://agent.tinyfish.ai', '/v1/datasets', {}, True),
 'list_datasets': ('GET',
                   'https://agent.tinyfish.ai',
                   '/v1/datasets',
                   {'limit': ('query', 'limit'), 'cursor': ('query', 'cursor')},
                   False),
 'get_dataset': ('GET', 'https://agent.tinyfish.ai', '/v1/datasets/{id}', {'id': ('path', 'id')}, False),
 'get_dataset_rows': ('GET',
                      'https://agent.tinyfish.ai',
                      '/v1/datasets/{id}/rows',
                      {'id': ('path', 'id'), 'limit': ('query', 'limit'), 'after': ('query', 'after')},
                      False),
 'populate_dataset': ('POST',
                      'https://agent.tinyfish.ai',
                      '/v1/datasets/{id}/populate',
                      {'id': ('path', 'id')},
                      True),
 'delete_dataset': ('DELETE',
                    'https://agent.tinyfish.ai',
                    '/v1/datasets/{id}',
                    {'id': ('path', 'id')},
                    False),
 'create_monitor': ('POST', 'https://agent.tinyfish.ai', '/v1/monitors', {}, True),
 'list_monitors': ('GET', 'https://agent.tinyfish.ai', '/v1/monitors', {}, False),
 'get_monitor': ('GET', 'https://agent.tinyfish.ai', '/v1/monitors/{id}', {'id': ('path', 'id')}, False),
 'update_monitor': ('PATCH', 'https://agent.tinyfish.ai', '/v1/monitors/{id}', {'id': ('path', 'id')}, True),
 'delete_monitor': ('DELETE',
                    'https://agent.tinyfish.ai',
                    '/v1/monitors/{id}',
                    {'id': ('path', 'id')},
                    False),
 'search': ('GET',
            'https://api.search.tinyfish.ai',
            '/',
            {'query': ('query', 'query'),
             'purpose': ('query', 'purpose'),
             'location': ('query', 'location'),
             'language': ('query', 'language'),
             'include_domains': ('query', 'include_domains'),
             'exclude_domains': ('query', 'exclude_domains'),
             'domain_type': ('query', 'domain_type'),
             'after_date': ('query', 'after_date'),
             'before_date': ('query', 'before_date'),
             'recency_minutes': ('query', 'recency_minutes'),
             'pub_year_min': ('query', 'pub_year_min'),
             'pub_year_max': ('query', 'pub_year_max'),
             'page': ('query', 'page'),
             'include_thumbnail': ('query', 'include_thumbnail'),
             'fetch': ('query', 'fetch')},
            False),
 'fetch_urls': ('POST', 'https://api.fetch.tinyfish.ai', '/', {}, True),
 'start_research': ('POST', 'https://agent.tinyfish.ai', '/v1/automation/run-research-async', {}, True),
 'get_research': ('GET',
                  'https://agent.tinyfish.ai',
                  '/v1/research-run/{research_run_id}',
                  {'research_run_id': ('path', 'research_run_id')},
                  False)}


class TinyfishNode(WorkflowNode):
    integration_type = "automation-tinyfish"
    credential_provider_labels = {"tinyfish": "TinyFish Account"}
    connection_evidence = ConnectionEvidence(
        noun="Tinyfish runs", operation="list_runs", label_keys=("goal", "run_id"))

    @classmethod
    def get_config_model(cls):
        return TinyfishFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Tinyfish API key")
        op = self.config.config
        method, origin, path, bindings, has_body = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        params = {}
        for field, (location, wire_name) in bindings.items():
            if field not in values:
                continue
            value = values.pop(field)
            if location == "path":
                path = path.replace("{" + wire_name + "}", quote(str(value), safe=""))
            else:
                params[wire_name] = value
        if op.operation == "create_monitor":
            values["config"] = {"url": values.pop("url")}
            values["type"] = "fetch"
        key = self.config.credentials.api_key
        # Fixed provider origins only; no redirects may forward the API key.
        async with guarded_async_client(timeout=180, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, origin + path,
                headers={"X-API-Key": key, "Accept": "application/json"},
                params=params, **({"json": values} if has_body else {}))
        if response.status_code == 204:
            data = None
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Tinyfish returned a non-JSON response") from None
        # Reading a failed run is a successful read: preserve its task error in data.
        run_record = op.operation in {"get_run", "get_research"} and isinstance(data, dict) and "status" in data
        if not 200 <= response.status_code < 300 or (isinstance(data, dict) and data.get("error") and not run_record):
            error = data.get("error") if isinstance(data, dict) else None
            message = error.get("message") if isinstance(error, dict) else error
            message = str(message or "Tinyfish request failed").replace(key, "[redacted]")
            output = {"status": "error", "http_status": response.status_code, "status_code": response.status_code, "message": message}
        else:
            if data is not None and not isinstance(data, (dict, list)):
                raise ValueError("Tinyfish returned an unexpected JSON response")
            output = {"status": "success", "http_status": response.status_code, "data": data}
        await self.emit(output)
        return output
