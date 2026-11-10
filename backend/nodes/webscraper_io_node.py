"""Web Scraper Cloud API 1.0.0, pinned from https://webscraper.io/openapi.yaml.

Each operation is one published endpoint. Requests stay on the provider's fixed
API origin; redirects and automatic mutation retries are disabled. List calls
return a single page and explicit pagination metadata.

Webhooks are configured manually in the provider UI; there is no documented
registration API. The list APIs have no created/updated time filter or ordering.
"""
from __future__ import annotations

import base64
import json
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.webscraper.io/api/v1"
CREDENTIAL_TYPE = "webscraper_io_api_token"


class WebscraperIoCredential(BaseModel):
    model_config = ConfigDict(title="Webscraper Io API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "api_key",
            "x-credential-url": "https://cloud.webscraper.io/api",
            "x-credential-instructions": "Copy your API token from the API page in Web Scraper Cloud. Paste the token without the Bearer prefix. NoClick uses it only with api.webscraper.io.",
        })
    credential_type: Literal["webscraper_io_api_token"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListSitemapsConfig(_Input):
    """Returns a paginated list of sitemaps for the authenticated user's organization."""
    operation: Literal["list_sitemaps"] = Field("list_sitemaps", title='Get sitemaps', json_schema_extra={"ui:hidden": True})
    tag: str | None = Field(None, title='Tag', min_length=1, max_length=4096)
    page: int | None = Field(None, title='Page', strict=True, ge=1)


class ImportSitemapConfig(_Input):
    """Imports a sitemap from raw JSON content and creates a new sitemap."""
    operation: Literal["import_sitemap"] = Field("import_sitemap", title='Import sitemap', json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, title='Name', min_length=1, max_length=4096)
    folder_id: int | None = Field(None, title='Folder Id', strict=True, ge=0)
    sitemap: dict[str, Any] = Field(..., title='Sitemap', description='Sitemap JSON exported from the Web Scraper extension.')


class GetSitemapConfig(_Input):
    """Returns details for a single sitemap by ID."""
    operation: Literal["get_sitemap"] = Field("get_sitemap", title='Get sitemap', json_schema_extra={"ui:hidden": True})
    sitemapId: int = Field(..., title='Sitemap Id', strict=True, ge=1)


class UpdateSitemapConfig(_Input):
    """Updates sitemap JSON for an existing sitemap."""
    operation: Literal["update_sitemap"] = Field("update_sitemap", title='Update sitemap', json_schema_extra={"ui:hidden": True})
    sitemapId: int = Field(..., title='Sitemap Id', strict=True, ge=1)
    sitemap: dict[str, Any] = Field(..., title='Sitemap', description='Sitemap JSON exported from the Web Scraper extension.')


class DeleteSitemapConfig(_Input):
    """Deletes a sitemap."""
    operation: Literal["delete_sitemap"] = Field("delete_sitemap", title='Delete sitemap', json_schema_extra={"ui:hidden": True})
    sitemapId: int = Field(..., title='Sitemap Id', strict=True, ge=1)


class RenameSitemapConfig(_Input):
    """Renames a sitemap and updates related scraping job sitemap names."""
    operation: Literal["rename_sitemap"] = Field("rename_sitemap", title='Rename sitemap', json_schema_extra={"ui:hidden": True})
    sitemapId: int = Field(..., title='Sitemap Id', strict=True, ge=1)
    name: str = Field(..., title='Name', min_length=1, max_length=4096)


class GetSchedulerConfig(_Input):
    """Returns scheduler configuration for a sitemap."""
    operation: Literal["get_scheduler"] = Field("get_scheduler", title='Get sitemap scheduler', json_schema_extra={"ui:hidden": True})
    sitemapId: int = Field(..., title='Sitemap Id', strict=True, ge=1)


class EnableSchedulerConfig(_Input):
    """Enables sitemap scheduler with the provided cron and execution settings."""
    operation: Literal["enable_scheduler"] = Field("enable_scheduler", title='Enable sitemap scheduler', json_schema_extra={"ui:hidden": True})
    sitemapId: int = Field(..., title='Sitemap Id', strict=True, ge=1)
    proxy: Literal['datacenter-de', 'datacenter-gb', 'datacenter-us', 'residential-ae', 'residential-ar', 'residential-at', 'residential-au', 'residential-be', 'residential-br', 'residential-ca', 'residential-ch', 'residential-cn', 'residential-cy', 'residential-cz', 'residential-de', 'residential-dk', 'residential-es', 'residential-fi', 'residential-fr', 'residential-gb', 'residential-gr', 'residential-hk', 'residential-hu', 'residential-id', 'residential-ie', 'residential-il', 'residential-in', 'residential-it', 'residential-jp', 'residential-kr', 'residential-mx', 'residential-nl', 'residential-no', 'residential-nz', 'residential-ph', 'residential-pl', 'residential-pt', 'residential-py', 'residential-ru', 'residential-sa', 'residential-se', 'residential-sg', 'residential-sk', 'residential-th', 'residential-tr', 'residential-tw', 'residential-ua', 'residential-us', 'residential-vn', 'residential-za'] = Field(..., title='Proxy')
    cron_minute: str = Field(..., title='Cron Minute', min_length=1, max_length=4096)
    cron_hour: str = Field(..., title='Cron Hour', min_length=1, max_length=4096)
    cron_day: str = Field(..., title='Cron Day', min_length=1, max_length=4096)
    cron_month: str = Field(..., title='Cron Month', min_length=1, max_length=4096)
    cron_weekday: str = Field(..., title='Cron Weekday', min_length=1, max_length=4096)
    request_interval: int = Field(..., title='Request Interval', strict=True, ge=500)
    page_load_delay: int = Field(..., title='Page Load Delay', strict=True, ge=500)
    cron_timezone: str = Field(..., title='Cron Timezone', min_length=1, max_length=4096)
    render_js: bool | None = Field(None, title='Render Js')
    priority: Literal[1, 2, 3, 4, 5] | None = Field(None, title='Priority')


class DisableSchedulerConfig(_Input):
    """Disables sitemap scheduler."""
    operation: Literal["disable_scheduler"] = Field("disable_scheduler", title='Disable sitemap scheduler', json_schema_extra={"ui:hidden": True})
    sitemapId: int = Field(..., title='Sitemap Id', strict=True, ge=1)


class ListTagsConfig(_Input):
    """Returns tags assigned to a sitemap."""
    operation: Literal["list_tags"] = Field("list_tags", title='Get sitemap tags', json_schema_extra={"ui:hidden": True})
    sitemapId: int = Field(..., title='Sitemap Id', strict=True, ge=1)


class AddTagConfig(_Input):
    """Adds a tag to a sitemap."""
    operation: Literal["add_tag"] = Field("add_tag", title='Add sitemap tag', json_schema_extra={"ui:hidden": True})
    sitemapId: int = Field(..., title='Sitemap Id', strict=True, ge=1)
    tag_name: str = Field(..., title='Tag Name', min_length=1, max_length=4096)


class RemoveTagConfig(_Input):
    """Removes a tag from a sitemap."""
    operation: Literal["remove_tag"] = Field("remove_tag", title='Remove sitemap tag', json_schema_extra={"ui:hidden": True})
    sitemapId: int = Field(..., title='Sitemap Id', strict=True, ge=1)
    tag_name: str = Field(..., title='Tag Name', min_length=1, max_length=4096)


class CreateScrapingJobConfig(_Input):
    """Creates a new scraping job for a sitemap."""
    operation: Literal["create_scraping_job"] = Field("create_scraping_job", title='Create scraping job', json_schema_extra={"ui:hidden": True})
    sitemap_id: int = Field(..., title='Sitemap Id', strict=True, ge=1)
    request_interval: int = Field(..., title='Request Interval', strict=True, ge=500)
    page_load_delay: int = Field(..., title='Page Load Delay', strict=True, ge=500)
    proxy: Literal['datacenter-de', 'datacenter-gb', 'datacenter-us', 'residential-ae', 'residential-ar', 'residential-at', 'residential-au', 'residential-be', 'residential-br', 'residential-ca', 'residential-ch', 'residential-cn', 'residential-cy', 'residential-cz', 'residential-de', 'residential-dk', 'residential-es', 'residential-fi', 'residential-fr', 'residential-gb', 'residential-gr', 'residential-hk', 'residential-hu', 'residential-id', 'residential-ie', 'residential-il', 'residential-in', 'residential-it', 'residential-jp', 'residential-kr', 'residential-mx', 'residential-nl', 'residential-no', 'residential-nz', 'residential-ph', 'residential-pl', 'residential-pt', 'residential-py', 'residential-ru', 'residential-sa', 'residential-se', 'residential-sg', 'residential-sk', 'residential-th', 'residential-tr', 'residential-tw', 'residential-ua', 'residential-us', 'residential-vn', 'residential-za'] = Field(..., title='Proxy')
    render_js: bool = Field(True, title='Render Js')
    priority: Literal[1, 2, 3, 4, 5] = Field(3, title='Priority')
    start_urls: list[str] | None = Field(None, title='Start Urls')
    custom_id: str | None = Field(None, title='Custom Id', min_length=1, max_length=4096)


class ListScrapingJobsConfig(_Input):
    """Returns a paginated list of scraping jobs for the authenticated user's organization."""
    operation: Literal["list_scraping_jobs"] = Field("list_scraping_jobs", title='Get scraping jobs', json_schema_extra={"ui:hidden": True})
    sitemap_id: int | None = Field(None, title='Sitemap Id', strict=True, ge=1)
    tag: str | None = Field(None, title='Tag', min_length=1, max_length=4096)
    status: Literal['started', 'finished', 'failed', 'stopped', 'waiting-to-be-scheduled'] | None = Field(None, title='Status', description='Filter jobs by status. Omit to return jobs of all statuses.')
    page: int | None = Field(None, title='Page', strict=True, ge=1)


class GetScrapingJobConfig(_Input):
    """Returns details for a single scraping job by ID"""
    operation: Literal["get_scraping_job"] = Field("get_scraping_job", title='Get scraping job', json_schema_extra={"ui:hidden": True})
    scrapingJobId: int = Field(..., title='Scrapingjob Id', strict=True, ge=1)


class DeleteScrapingJobConfig(_Input):
    """Deletes a scraping job."""
    operation: Literal["delete_scraping_job"] = Field("delete_scraping_job", title='Delete scraping job', json_schema_extra={"ui:hidden": True})
    scrapingJobId: int = Field(..., title='Scrapingjob Id', strict=True, ge=1)


class ListProblematicUrlsConfig(_Input):
    """Returns a paginated list of problematic URLs for the scraping job."""
    operation: Literal["list_problematic_urls"] = Field("list_problematic_urls", title='Get scraping job problematic URLs', json_schema_extra={"ui:hidden": True})
    scrapingJobId: int = Field(..., title='Scrapingjob Id', strict=True, ge=1)
    page: int | None = Field(None, title='Page', strict=True, ge=1)


class DownloadDataConfig(_Input):
    """Streams scraping job data as a downloadable file."""
    operation: Literal["download_data"] = Field("download_data", title='Download scraping job data', json_schema_extra={"ui:hidden": True})
    scrapingJobId: int = Field(..., title='Scrapingjob Id', strict=True, ge=1)
    extension: Literal['json', 'csv', 'xlsx'] = Field(..., title='Extension')
    raw: Literal['true', 'false'] | None = Field(None, title='Raw', description='Return raw exported data format when set to `true`.')


class GetDataQualityConfig(_Input):
    """Returns data quality statistics for a scraping job."""
    operation: Literal["get_data_quality"] = Field("get_data_quality", title='Get scraping job data quality', json_schema_extra={"ui:hidden": True})
    scrapingJobId: int = Field(..., title='Scrapingjob Id', strict=True, ge=1)


class ContinueScrapingJobConfig(_Input):
    """Continues a stopped or pausable scraping job. All parameters are optional. Any parameter that is not provided keeps the scraping job's current value."""
    operation: Literal["continue_scraping_job"] = Field("continue_scraping_job", title='Continue scraping job', json_schema_extra={"ui:hidden": True})
    scrapingJobId: int = Field(..., title='Scrapingjob Id', strict=True, ge=1)
    request_interval: int | None = Field(None, title='Request Interval', strict=True, ge=500)
    page_load_delay: int | None = Field(None, title='Page Load Delay', strict=True, ge=500)
    render_js: bool | None = Field(None, title='Render Js')
    proxy: Literal['datacenter-de', 'datacenter-gb', 'datacenter-us', 'residential-ae', 'residential-ar', 'residential-at', 'residential-au', 'residential-be', 'residential-br', 'residential-ca', 'residential-ch', 'residential-cn', 'residential-cy', 'residential-cz', 'residential-de', 'residential-dk', 'residential-es', 'residential-fi', 'residential-fr', 'residential-gb', 'residential-gr', 'residential-hk', 'residential-hu', 'residential-id', 'residential-ie', 'residential-il', 'residential-in', 'residential-it', 'residential-jp', 'residential-kr', 'residential-mx', 'residential-nl', 'residential-no', 'residential-nz', 'residential-ph', 'residential-pl', 'residential-pt', 'residential-py', 'residential-ru', 'residential-sa', 'residential-se', 'residential-sg', 'residential-sk', 'residential-th', 'residential-tr', 'residential-tw', 'residential-ua', 'residential-us', 'residential-vn', 'residential-za'] | None = Field(None, title='Proxy')
    priority: Literal[1, 2, 3, 4, 5] | None = Field(None, title='Priority')


class StopScrapingJobConfig(_Input):
    """Stops a running or pausable scraping job."""
    operation: Literal["stop_scraping_job"] = Field("stop_scraping_job", title='Stop scraping job', json_schema_extra={"ui:hidden": True})
    scrapingJobId: int = Field(..., title='Scrapingjob Id', strict=True, ge=1)


class GetAccountConfig(_Input):
    """Returns account details for the authenticated user."""
    operation: Literal["get_account"] = Field("get_account", title='Get account info', json_schema_extra={"ui:hidden": True})


OPERATIONS = {'list_sitemaps': {'method': 'GET',
                   'path': '/sitemaps',
                   'path_fields': [],
                   'query_fields': ['tag', 'page'],
                   'body_fields': [],
                   'raw_sitemap': False},
 'import_sitemap': {'method': 'POST',
                    'path': '/sitemap',
                    'path_fields': [],
                    'query_fields': ['name', 'folder_id'],
                    'body_fields': ['sitemap'],
                    'raw_sitemap': True},
 'get_sitemap': {'method': 'GET',
                 'path': '/sitemap/{sitemapId}',
                 'path_fields': ['sitemapId'],
                 'query_fields': [],
                 'body_fields': [],
                 'raw_sitemap': False},
 'update_sitemap': {'method': 'PUT',
                    'path': '/sitemap/{sitemapId}',
                    'path_fields': ['sitemapId'],
                    'query_fields': [],
                    'body_fields': ['sitemap'],
                    'raw_sitemap': True},
 'delete_sitemap': {'method': 'DELETE',
                    'path': '/sitemap/{sitemapId}',
                    'path_fields': ['sitemapId'],
                    'query_fields': [],
                    'body_fields': [],
                    'raw_sitemap': False},
 'rename_sitemap': {'method': 'PUT',
                    'path': '/sitemap/{sitemapId}/rename',
                    'path_fields': ['sitemapId'],
                    'query_fields': [],
                    'body_fields': ['name'],
                    'raw_sitemap': False},
 'get_scheduler': {'method': 'GET',
                   'path': '/sitemap/{sitemapId}/scheduler',
                   'path_fields': ['sitemapId'],
                   'query_fields': [],
                   'body_fields': [],
                   'raw_sitemap': False},
 'enable_scheduler': {'method': 'POST',
                      'path': '/sitemap/{sitemapId}/enable-scheduler',
                      'path_fields': ['sitemapId'],
                      'query_fields': [],
                      'body_fields': ['proxy',
                                      'cron_minute',
                                      'cron_hour',
                                      'cron_day',
                                      'cron_month',
                                      'cron_weekday',
                                      'request_interval',
                                      'page_load_delay',
                                      'cron_timezone',
                                      'render_js',
                                      'priority'],
                      'raw_sitemap': False},
 'disable_scheduler': {'method': 'POST',
                       'path': '/sitemap/{sitemapId}/disable-scheduler',
                       'path_fields': ['sitemapId'],
                       'query_fields': [],
                       'body_fields': [],
                       'raw_sitemap': False},
 'list_tags': {'method': 'GET',
               'path': '/sitemap/{sitemapId}/tags',
               'path_fields': ['sitemapId'],
               'query_fields': [],
               'body_fields': [],
               'raw_sitemap': False},
 'add_tag': {'method': 'POST',
             'path': '/sitemap/{sitemapId}/add-tag',
             'path_fields': ['sitemapId'],
             'query_fields': [],
             'body_fields': ['tag_name'],
             'raw_sitemap': False},
 'remove_tag': {'method': 'DELETE',
                'path': '/sitemap/{sitemapId}/remove-tag',
                'path_fields': ['sitemapId'],
                'query_fields': [],
                'body_fields': ['tag_name'],
                'raw_sitemap': False},
 'create_scraping_job': {'method': 'POST',
                         'path': '/scraping-job',
                         'path_fields': [],
                         'query_fields': [],
                         'body_fields': ['sitemap_id',
                                         'request_interval',
                                         'page_load_delay',
                                         'proxy',
                                         'render_js',
                                         'priority',
                                         'start_urls',
                                         'custom_id'],
                         'raw_sitemap': False},
 'list_scraping_jobs': {'method': 'GET',
                        'path': '/scraping-jobs',
                        'path_fields': [],
                        'query_fields': ['sitemap_id', 'tag', 'status', 'page'],
                        'body_fields': [],
                        'raw_sitemap': False},
 'get_scraping_job': {'method': 'GET',
                      'path': '/scraping-job/{scrapingJobId}',
                      'path_fields': ['scrapingJobId'],
                      'query_fields': [],
                      'body_fields': [],
                      'raw_sitemap': False},
 'delete_scraping_job': {'method': 'DELETE',
                         'path': '/scraping-job/{scrapingJobId}',
                         'path_fields': ['scrapingJobId'],
                         'query_fields': [],
                         'body_fields': [],
                         'raw_sitemap': False},
 'list_problematic_urls': {'method': 'GET',
                           'path': '/scraping-job/{scrapingJobId}/problematic-urls',
                           'path_fields': ['scrapingJobId'],
                           'query_fields': ['page'],
                           'body_fields': [],
                           'raw_sitemap': False},
 'download_data': {'method': 'GET',
                   'path': '/scraping-job/{scrapingJobId}/{extension}',
                   'path_fields': ['scrapingJobId', 'extension'],
                   'query_fields': ['raw'],
                   'body_fields': [],
                   'raw_sitemap': False},
 'get_data_quality': {'method': 'GET',
                      'path': '/scraping-job/{scrapingJobId}/data-quality',
                      'path_fields': ['scrapingJobId'],
                      'query_fields': [],
                      'body_fields': [],
                      'raw_sitemap': False},
 'continue_scraping_job': {'method': 'POST',
                           'path': '/scraping-job/{scrapingJobId}/continue',
                           'path_fields': ['scrapingJobId'],
                           'query_fields': [],
                           'body_fields': ['request_interval',
                                           'page_load_delay',
                                           'render_js',
                                           'proxy',
                                           'priority'],
                           'raw_sitemap': False},
 'stop_scraping_job': {'method': 'POST',
                       'path': '/scraping-job/{scrapingJobId}/stop',
                       'path_fields': ['scrapingJobId'],
                       'query_fields': [],
                       'body_fields': [],
                       'raw_sitemap': False},
 'get_account': {'method': 'GET',
                 'path': '/account',
                 'path_fields': [],
                 'query_fields': [],
                 'body_fields': [],
                 'raw_sitemap': False}}

WebscraperIoOperation = Annotated[Union[ListSitemapsConfig, ImportSitemapConfig, GetSitemapConfig, UpdateSitemapConfig, DeleteSitemapConfig, RenameSitemapConfig, GetSchedulerConfig, EnableSchedulerConfig, DisableSchedulerConfig, ListTagsConfig, AddTagConfig, RemoveTagConfig, CreateScrapingJobConfig, ListScrapingJobsConfig, GetScrapingJobConfig, DeleteScrapingJobConfig, ListProblematicUrlsConfig, DownloadDataConfig, GetDataQualityConfig, ContinueScrapingJobConfig, StopScrapingJobConfig, GetAccountConfig], Field(discriminator="operation")]


class WebscraperIoConfig(NodeConfig[WebscraperIoOperation, WebscraperIoCredential]):
    pass


class WebscraperIoNode(WorkflowNode):
    integration_type = "automation-webscraper-io"
    connection_evidence = ConnectionEvidence(
        noun="sitemaps", operation="list_sitemaps", identity_operation="get_account",
        identity_keys=("email",),
    )

    @classmethod
    def get_config_model(cls):
        return WebscraperIoConfig

    @classmethod
    def parse_config(cls, config_data):
        return super().parse_config(runtime_config_view(config_data, WebscraperIoConfig))

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Webscraper Io API token")
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec["path"]
        for field in spec["path_fields"]:
            path = path.replace("{" + field + "}", str(values[field]))
        params = {field: values[field] for field in spec["query_fields"] if field in values}
        body = {field: values[field] for field in spec["body_fields"] if field in values}
        if spec["raw_sitemap"]:
            body = body["sitemap"]
        kwargs = {"params": params}
        if spec["body_fields"]:
            kwargs["json"] = body
        headers = {"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"}
        if config.operation == "download_data":
            headers["Accept"] = {"json": "application/jsonl", "csv": "text/csv",
                "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}[config.extension]
        async with guarded_async_client(verify=True, trust_env=False, follow_redirects=False,
                timeout=httpx.Timeout(30.0)) as client:
            async with client.stream(spec["method"], BASE + path, headers=headers, **kwargs) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 20_000_000:
                        raise ValueError("Webscraper Io response exceeds 20 MB; narrow the job or download it directly")
                if response.status_code != 200:
                    message = "Webscraper Io request failed"
                    try:
                        error = json.loads(raw)
                        if isinstance(error, dict) and isinstance(error.get("error"), str):
                            message = error["error"][:2000].replace(credential.api_token, "[redacted]")
                    except (ValueError, UnicodeError):
                        pass
                    return {"status": "error", "http_status": response.status_code, "error": message}
                if config.operation == "download_data":
                    return {"status": "success", "extension": config.extension,
                        "encoding": "base64" if config.extension == "xlsx" else "utf-8",
                        "content": base64.b64encode(raw).decode() if config.extension == "xlsx" else raw.decode("utf-8")}
                result = json.loads(raw)
        if not isinstance(result, dict) or result.get("success") is not True or "data" not in result:
            message = result.get("error") if isinstance(result, dict) else None
            return {"status": "error", "error": message[:2000].replace(credential.api_token, "[redacted]")
                if isinstance(message, str) else "Webscraper Io returned an unexpected response"}
        if config.operation in {"list_sitemaps", "list_scraping_jobs", "list_problematic_urls", "list_tags"}:
            if not isinstance(result["data"], list):
                raise ValueError("Webscraper Io did not return a list")
        return {"status": "success", **result}
