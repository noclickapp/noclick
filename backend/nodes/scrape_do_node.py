"""Scrape.do Async API, pinned to the provider's six-operation 0.1.0 contract."""
from __future__ import annotations

import base64
from datetime import datetime
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput, snapshot_safe
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://q.scrape.do"
Status = Literal["queuing", "queued", "pending", "rotating", "success", "error", "canceled"]


class ScrapeDoTokenCredential(BaseModel):
    model_config = ConfigDict(title="Scrape Do API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.scrape.do/",
            "x-credential-instructions": "Paste the API token from your Scrape.do dashboard. NoClick sends it in the X-Token header to the Async API."
        })
    credential_type: Literal["scrape_do_api_token"] = Field("scrape_do_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class RenderOptions(_Input):
    BlockResources: Optional[bool] = None
    WaitUntil: Optional[Literal["domcontentloaded", "networkidle0", "networkidle2"]] = None
    CustomWait: Optional[int] = Field(None, ge=0, le=35000)
    WaitSelector: Optional[str] = None
    PlayWithBrowser: Optional[list[dict]] = None
    ReturnJSON: Optional[bool] = None
    ShowWebsocketRequests: Optional[bool] = None
    ShowFrames: Optional[bool] = None
    Screenshot: Optional[bool] = None
    FullScreenshot: Optional[bool] = None
    ParticularScreenshot: Optional[str] = None


class CreateJob(_Input):
    """Submit a batch of URLs for asynchronous scraping; does not wait for completion."""
    operation: Literal["create_job"] = Field("create_job", json_schema_extra={"ui:hidden": True})
    targets: list[str] = Field(..., min_length=1, title="Target URLs", description="URLs to scrape, for example https://httpbin.co/anything.")
    method: Literal["GET", "POST", "PUT", "PATCH", "HEAD", "DELETE"] = "GET"
    body: Optional[str] = None
    geo_code: Optional[str] = None
    regional_geo_code: Optional[str] = None
    super_proxy: Optional[bool] = Field(None, title="Residential proxies")
    headers: Optional[dict[str, str]] = None
    forward_headers: Optional[bool] = None
    session_id: Optional[str] = None
    device: Optional[Literal["desktop", "mobile", "tablet"]] = None
    set_cookies: Optional[str] = None
    timeout: Optional[int] = Field(None, title="Timeout (milliseconds)")
    retry_timeout: Optional[int] = Field(None, title="Retry timeout (milliseconds)")
    disable_retry: Optional[bool] = None
    transparent_response: Optional[bool] = None
    disable_redirection: Optional[bool] = None
    output: Optional[Literal["raw", "markdown"]] = None
    render: Optional[RenderOptions] = None
    webhook_url: Optional[str] = None
    webhook_headers: Optional[dict[str, str]] = None

    @field_validator("targets")
    @classmethod
    def urls(cls, values):
        for value in values:
            u = urlsplit(value)
            if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password:
                raise ValueError("Targets must be HTTP or HTTPS URLs without embedded credentials")
        return values

    @model_validator(mode="after")
    def exclusive_cookies(self):
        if self.set_cookies and self.headers:
            raise ValueError("Set cookies and custom headers cannot be used together")
        return self


class ListJobs(_Input):
    """List one page of the connected account's jobs, with optional filters."""
    operation: Literal["list_jobs"] = Field("list_jobs", json_schema_extra={"ui:hidden": True})
    page_size: int = Field(10, ge=1, le=100)
    page: int = Field(1, ge=1)
    status: Optional[Status] = None
    start_from: Optional[str] = Field(None, description="RFC3339 timestamp, e.g. 2025-01-01T00:00:00Z")
    start_to: Optional[str] = Field(None, description="RFC3339 timestamp, e.g. 2025-01-31T23:59:59Z")
    sort: Optional[Literal["start_time_asc", "start_time_desc"]] = None

    @field_validator("start_from", "start_to")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Include a timezone in RFC3339 timestamps")
        return value


class _Job(_Input):
    job_id: str = Field(..., title="Job ID", description="UUID returned by Create Job")

    @field_validator("job_id")
    @classmethod
    def uuid(cls, value):
        UUID(value)
        return value


class GetJob(_Job):
    """Get job status and its task list."""
    operation: Literal["get_job"] = Field("get_job", json_schema_extra={"ui:hidden": True})


class CancelJob(_Job):
    """Cancel a running job. Completed or canceled jobs can return HTTP 406."""
    operation: Literal["cancel_job"] = Field("cancel_job", json_schema_extra={"ui:hidden": True})


class GetTask(_Job):
    """Retrieve a task's scraped content and metadata before it expires."""
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"ui:hidden": True})
    task_id: str = Field(..., min_length=1, title="Task ID")

    @field_validator("task_id")
    @classmethod
    def segment(cls, value):
        if value in {".", ".."} or any(c in value for c in "/?#\\"):
            raise ValueError("Use one task identifier")
        return value


class GetMe(_Input):
    """Read account concurrency, active jobs and available credits."""
    operation: Literal["get_me"] = Field("get_me", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[CreateJob, ListJobs, GetJob, CancelJob, GetTask, GetMe], Field(discriminator="operation")]


class ScrapeDoConfig(NodeConfig[Operation, ScrapeDoTokenCredential]):
    pass


BODY_FIELDS = {
    "targets": "Targets", "method": "Method", "body": "Body", "geo_code": "GeoCode",
    "regional_geo_code": "RegionalGeoCode", "super_proxy": "Super", "headers": "Headers",
    "forward_headers": "ForwardHeaders", "session_id": "SessionID", "device": "Device",
    "set_cookies": "SetCookies", "timeout": "Timeout", "retry_timeout": "RetryTimeout",
    "disable_retry": "DisableRetry", "transparent_response": "TransparentResponse",
    "disable_redirection": "DisableRedirection", "output": "Output", "render": "Render",
    "webhook_url": "WebhookURL", "webhook_headers": "WebhookHeaders",
}


class ScrapeDoNode(WorkflowNode):
    integration_type = "automation-scrape-do"
    connection_evidence = ConnectionEvidence(noun="scraping jobs", operation="list_jobs", label_keys=("JobID",))

    @classmethod
    def get_config_model(cls):
        return ScrapeDoConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Scrape Do API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, path, params, body = "GET", "/api/v1/jobs", None, None
        if isinstance(config, CreateJob):
            method = "POST"
            body = {BODY_FIELDS[k]: v for k, v in config.model_dump(exclude_none=True).items() if k != "operation"}
        elif isinstance(config, ListJobs):
            params = config.model_dump(exclude={"operation"}, exclude_none=True)
        elif isinstance(config, GetMe):
            path = "/api/v1/me"
        else:
            path += "/" + quote(config.job_id, safe="")
            if isinstance(config, CancelJob):
                method = "DELETE"
            elif isinstance(config, GetTask):
                path += "/" + quote(config.task_id, safe="")
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"X-Token": token, "Accept": "application/json"}, params=params, json=body)
        except (httpx.HTTPError, OSError):
            raise ValueError("Scrape Do request did not complete; check job state before retrying a write") from None
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Scrape Do returned a non-JSON response") from None
        if not 200 <= response.status_code < 300 or (isinstance(data, dict) and data.get("Error")):
            message = data.get("Error", "Request rejected") if isinstance(data, dict) else "Request rejected"
            raise ValueError(f"Scrape Do HTTP {response.status_code}: {str(message).replace(token, '[redacted]')}")
        if not isinstance(data, dict):
            raise ValueError("Scrape Do returned an unexpected response shape")
        result = {"status": "success", "data": data}
        if isinstance(config, ListJobs):
            if not isinstance(data.get("Jobs"), list):
                raise ValueError("Scrape Do job list is missing Jobs")
            result["items"] = data["Jobs"]
        if isinstance(config, GetTask) and data.get("Base64EncodedContent") is True:
            content = data.get("Content")
            if not isinstance(content, str):
                raise ValueError("Scrape Do encoded task content is missing")
            try:
                raw = base64.b64decode(content + "=" * (-len(content) % 4), validate=True)
            except ValueError:
                raise ValueError("Scrape Do task content is invalid base64") from None
            data = {k: v for k, v in data.items() if k != "Content"}
            mime = next((v for k, v in data.get("ResponseHeaders", {}).items() if k.lower() == "content-type"), "application/octet-stream")
            data["file"] = BinaryOutput(raw, mime, "scrape-do-task")
            result["data"] = data
        await self.emit(snapshot_safe(result))
        return result
