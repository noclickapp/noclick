"""Hyperbrowser API-key automation against the published v1 API contract."""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.hyperbrowser.ai"


class HyperbrowserApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Hyperbrowser API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.hyperbrowser.ai/",
            "x-credential-instructions": "Copy an API key from your Hyperbrowser dashboard. NoClick sends it as x-api-key to api.hyperbrowser.ai. Connecting reads your team's sessions."})
    credential_type: Literal["hyperbrowser_api_key"] = Field("hyperbrowser_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class SessionProfile(_Input):
    id: str = Field(..., min_length=1, title="Profile ID")
    persistChanges: bool | None = None
    persistNetworkCache: bool | None = None


class SessionOptions(_Input):
    useStealth: bool | None = None
    useProxy: bool | None = None
    solveCaptchas: bool | None = None
    adblock: bool | None = None
    acceptCookies: bool | None = None
    enableWebRecording: bool | None = None
    enableVideoWebRecording: bool | None = None
    saveDownloads: bool | None = None
    region: Literal["us", "us-central", "us-west", "us-east", "asia-south", "europe-west"] | None = None
    profile: SessionProfile | None = None


class ScrapeOptions(_Input):
    formats: list[Literal["html", "links", "markdown", "screenshot"]] | None = None
    includeTags: list[str] | None = None
    excludeTags: list[str] | None = None
    onlyMainContent: bool | None = None
    waitFor: float | None = Field(None, ge=0)
    timeout: float | None = Field(None, gt=0)
    waitUntil: Literal["load", "domcontentloaded", "networkidle"] | None = None


class _SessionID(_Input):
    session_id: str = Field(..., min_length=1, title="Session ID")


class _ProfileID(_Input):
    profile_id: str = Field(..., min_length=1, title="Profile ID")


class _JobID(_Input):
    job_id: str = Field(..., min_length=1, title="Job ID")


class _Scrape(_Input):
    url: str = Field(..., min_length=1, title="URL")
    sessionOptions: SessionOptions | None = None
    scrapeOptions: ScrapeOptions | None = None


class CreateSessionConfig(SessionOptions):
    operation: Literal["create_session"] = Field("create_session", title="Create Session", json_schema_extra={"ui:hidden": True})


class GetSessionConfig(_SessionID):
    operation: Literal["get_session"] = Field("get_session", title="Get Session", json_schema_extra={"ui:hidden": True})


class StopSessionConfig(_SessionID):
    operation: Literal["stop_session"] = Field("stop_session", title="Stop Session", json_schema_extra={"ui:hidden": True})


class ListSessionsConfig(_Input):
    operation: Literal["list_sessions"] = Field("list_sessions", title="List Sessions", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    status: Literal["active", "closed", "error", "close-error"] | None = None


class GetSessionRecordingConfig(_SessionID):
    operation: Literal["get_session_recording"] = Field("get_session_recording", title="Get Session Recording", json_schema_extra={"ui:hidden": True})


class GetSessionVideoConfig(_SessionID):
    operation: Literal["get_session_video"] = Field("get_session_video", title="Get Session Video", json_schema_extra={"ui:hidden": True})


class GetSessionDownloadsConfig(_SessionID):
    operation: Literal["get_session_downloads"] = Field("get_session_downloads", title="Get Session Downloads", json_schema_extra={"ui:hidden": True})


class CreateProfileConfig(_Input):
    operation: Literal["create_profile"] = Field("create_profile", title="Create Profile", json_schema_extra={"ui:hidden": True})
    name: str | None = None


class GetProfileConfig(_ProfileID):
    operation: Literal["get_profile"] = Field("get_profile", title="Get Profile", json_schema_extra={"ui:hidden": True})


class DeleteProfileConfig(_ProfileID):
    operation: Literal["delete_profile"] = Field("delete_profile", title="Delete Profile", json_schema_extra={"ui:hidden": True})


class ListProfilesConfig(_Input):
    operation: Literal["list_profiles"] = Field("list_profiles", title="List Profiles", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    limit: int = Field(10, ge=1)
    name: str | None = None


class StartScrapeConfig(_Scrape):
    operation: Literal["start_scrape"] = Field("start_scrape", title="Start Scrape", json_schema_extra={"ui:hidden": True})


class GetScrapeConfig(_JobID):
    job_id: UUID = Field(..., title="Scrape Job ID")
    operation: Literal["get_scrape"] = Field("get_scrape", title="Get Scrape", json_schema_extra={"ui:hidden": True})


class GetScrapeStatusConfig(_JobID):
    job_id: UUID = Field(..., title="Scrape Job ID")
    operation: Literal["get_scrape_status"] = Field("get_scrape_status", title="Get Scrape Status", json_schema_extra={"ui:hidden": True})


class StartBatchScrapeConfig(_Input):
    operation: Literal["start_batch_scrape"] = Field("start_batch_scrape", title="Start Batch Scrape", json_schema_extra={"ui:hidden": True})
    urls: list[str] = Field(..., min_length=1)
    sessionOptions: SessionOptions | None = None
    scrapeOptions: ScrapeOptions | None = None


class GetBatchScrapeConfig(_JobID):
    operation: Literal["get_batch_scrape"] = Field("get_batch_scrape", title="Get Batch Scrape", json_schema_extra={"ui:hidden": True})


class StartCrawlConfig(_Scrape):
    operation: Literal["start_crawl"] = Field("start_crawl", title="Start Crawl", json_schema_extra={"ui:hidden": True})
    maxPages: int | None = Field(None, ge=1)
    followLinks: bool | None = None
    ignoreSitemap: bool | None = None
    excludePatterns: list[str] | None = None
    includePatterns: list[str] | None = None


class GetCrawlConfig(_JobID):
    operation: Literal["get_crawl"] = Field("get_crawl", title="Get Crawl", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, ge=0)
    batchSize: int | None = Field(None, ge=1)


class StartExtractConfig(_Input):
    operation: Literal["start_extract"] = Field("start_extract", title="Start Extract", json_schema_extra={"ui:hidden": True})
    urls: list[str] = Field(..., min_length=1)
    prompt: str | None = None
    systemPrompt: str | None = None
    maxLinks: float | None = Field(None, ge=0)
    extraction_schema: dict | None = Field(None, alias="schema", title="Extraction JSON Schema")
    sessionOptions: SessionOptions | None = None
    waitFor: float | None = Field(None, ge=0)


class GetExtractConfig(_JobID):
    operation: Literal["get_extract"] = Field("get_extract", title="Get Extract", json_schema_extra={"ui:hidden": True})


class StartHyperAgentConfig(_Input):
    operation: Literal["start_hyper_agent"] = Field("start_hyper_agent", title="Start Hyper Agent", json_schema_extra={"ui:hidden": True})
    task: str = Field(..., min_length=1)
    maxSteps: int | None = Field(None, ge=1)
    sessionId: str | None = None
    keepBrowserOpen: bool | None = None
    sessionOptions: SessionOptions | None = None
    version: Literal["0.8.0", "1.1.0"] | None = None


class GetHyperAgentConfig(_JobID):
    operation: Literal["get_hyper_agent"] = Field("get_hyper_agent", title="Get Hyper Agent", json_schema_extra={"ui:hidden": True})


class StopHyperAgentConfig(_JobID):
    operation: Literal["stop_hyper_agent"] = Field("stop_hyper_agent", title="Stop Hyper Agent", json_schema_extra={"ui:hidden": True})


class FetchPageConfig(_Input):
    operation: Literal["fetch_page"] = Field("fetch_page", title="Fetch Page", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1)
    stealth: Literal["none", "auto", "ultra"] | None = None


class SearchWebConfig(_Input):
    operation: Literal["search_web"] = Field("search_web", title="Search Web", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1)
    page: int | None = Field(None, ge=1)
    maxAgeSeconds: int | None = Field(None, ge=0)


HyperbrowserConfig = Annotated[Union[
    CreateSessionConfig,
    GetSessionConfig,
    StopSessionConfig,
    ListSessionsConfig,
    GetSessionRecordingConfig,
    GetSessionVideoConfig,
    GetSessionDownloadsConfig,
    CreateProfileConfig,
    GetProfileConfig,
    DeleteProfileConfig,
    ListProfilesConfig,
    StartScrapeConfig,
    GetScrapeConfig,
    GetScrapeStatusConfig,
    StartBatchScrapeConfig,
    GetBatchScrapeConfig,
    StartCrawlConfig,
    GetCrawlConfig,
    StartExtractConfig,
    GetExtractConfig,
    StartHyperAgentConfig,
    GetHyperAgentConfig,
    StopHyperAgentConfig,
    FetchPageConfig,
    SearchWebConfig
], Field(discriminator="operation")]


class HyperbrowserFullConfig(NodeConfig[HyperbrowserConfig, HyperbrowserApiKeyCredential]):
    pass


OPERATIONS = {'create_session': ('POST', '/api/session'),
 'get_session': ('GET', '/api/session/{id}'),
 'stop_session': ('PUT', '/api/session/{id}/stop'),
 'list_sessions': ('GET', '/api/sessions'),
 'get_session_recording': ('GET', '/api/session/{id}/recording-url'),
 'get_session_video': ('GET', '/api/session/{id}/video-recording-url'),
 'get_session_downloads': ('GET', '/api/session/{id}/downloads-url'),
 'create_profile': ('POST', '/api/profile'),
 'get_profile': ('GET', '/api/profile/{id}'),
 'delete_profile': ('DELETE', '/api/profile/{id}'),
 'list_profiles': ('GET', '/api/profiles'),
 'start_scrape': ('POST', '/api/scrape'),
 'get_scrape': ('GET', '/api/scrape/{id}'),
 'get_scrape_status': ('GET', '/api/scrape/{id}/status'),
 'start_batch_scrape': ('POST', '/api/scrape/batch'),
 'get_batch_scrape': ('GET', '/api/scrape/batch/{id}'),
 'start_crawl': ('POST', '/api/crawl'),
 'get_crawl': ('GET', '/api/crawl/{id}'),
 'start_extract': ('POST', '/api/extract'),
 'get_extract': ('GET', '/api/extract/{id}'),
 'start_hyper_agent': ('POST', '/api/task/hyper-agent'),
 'get_hyper_agent': ('GET', '/api/task/hyper-agent/{id}'),
 'stop_hyper_agent': ('PUT', '/api/task/hyper-agent/{id}/stop'),
 'fetch_page': ('POST', '/api/web/fetch'),
 'search_web': ('POST', '/api/web/search')}


class HyperbrowserNode(WorkflowNode):
    integration_type = "automation-hyperbrowser"
    connection_evidence = ConnectionEvidence(operation="list_sessions", noun="browser sessions")

    @classmethod
    def get_config_model(cls):
        return HyperbrowserFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Hyperbrowser API key")
        config = self.config.config
        method, path = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", by_alias=True, exclude_none=True, exclude={"operation"})
        for field in ("session_id", "profile_id", "job_id"):
            if field in values:
                value = values.pop(field)
                if value in {".", ".."} or any(c in value for c in "/\\?#"):
                    raise ValueError("Use a single Hyperbrowser resource ID")
                path = path.replace("{id}", quote(value, safe=""))
        key = self.config.credentials.api_key
        async with guarded_async_client(timeout=120, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"x-api-key": key, "Accept": "application/json"},
                **({"params": values} if method == "GET" else {"json": values} if method == "POST" else {}))
        if not 200 <= response.status_code < 300:
            message = response.text.replace(key, "[redacted]")[:1000]
            raise ValueError(f"Hyperbrowser HTTP {response.status_code}: {message}")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Hyperbrowser returned invalid JSON") from None
        if not isinstance(body, dict):
            raise ValueError("Hyperbrowser returned an unexpected response shape")
        if body.get("success") is False:
            raise ValueError("Hyperbrowser did not confirm the operation")
        output = {"status": "success", "data": body}
        list_key = {"list_sessions": "sessions", "list_profiles": "profiles"}.get(config.operation)
        if list_key:
            if not isinstance(body.get(list_key), list):
                raise ValueError("Hyperbrowser list response is missing its resources")
            output["items"] = body[list_key]
        await self.emit(output)
        return output
