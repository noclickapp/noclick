"""ZenRows Batch API v0.2.0; one provider request per operation.

Contract: https://raw.githubusercontent.com/ZenRows/zenrows-python-sdk/main/docs/openapi.yaml
Results are one page; echo next_cursor to continue. Writes never retry automatically.
"""
from __future__ import annotations
import json
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://async.api.zenrows.com/v1"
ULID = Annotated[str, Field(pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$")]
def _task_segment(value):
    if value in {".", ".."}:
        raise ValueError("Use a task ID, not a dot path segment")
    return value


TaskID = Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,128}$"), AfterValidator(_task_segment)]
ExternalID = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")]
Metadata = Annotated[dict[str, Annotated[str, Field(max_length=1024)]], Field(max_length=20)]
ParamName = Literal["mode", "js_render", "js_instructions", "custom_headers", "premium_proxy", "proxy_country", "session_id", "original_status", "allowed_status_codes", "wait_for", "wait", "block_resources", "json_response", "css_extractor", "autoparse", "extract", "extract_fields", "response_type", "outputs"]
ScraperParams = dict[ParamName, Union[StrictStr, StrictBool, StrictInt, dict[str, str]]]


def _url(value: str, *, https=False):
    parsed = urlsplit(value)
    if parsed.scheme not in ({"https"} if https else {"http", "https"}) or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use a complete HTTPS URL" if https else "Use a complete HTTP or HTTPS URL")
    return value


class ZenrowsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Zenrows API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.zenrows.com/builder",
        "x-credential-instructions": "Copy your ZenRows API key from your dashboard and paste it here. NoClick sends it in the X-API-Key header to the ZenRows Batch API. Connecting reads your jobs; submitted scraping jobs consume your ZenRows credits.",
    })
    credential_type: Literal["zenrows_api_key"] = Field("zenrows_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Task(_Input):
    url: str = Field(..., max_length=2048)
    external_id: ExternalID | None = None
    metadata: Metadata | None = None
    method: Literal["GET", "POST"] = "GET"
    body: object | None = Field(None, description="POST body, at most 16 KiB. Use POST only for safe, idempotent queries: ZenRows may retry tasks.")
    zenrows_params: ScraperParams | None = None

    @field_validator("url")
    @classmethod
    def url_valid(cls, value):
        return _url(value)

    @model_validator(mode="after")
    def body_valid(self):
        if self.body is not None and (self.method != "POST" or len(json.dumps(self.body).encode()) > 16384):
            raise ValueError("Bodies require POST and must fit in 16 KiB")
        return self


class Webhook(_Input):
    url: str
    signature: StrictBool = Field(..., description="Enable only after configuring an active ZenRows HMAC key.")

    @field_validator("url")
    @classmethod
    def url_valid(cls, value):
        return _url(value, https=True)


class Rate(_Input):
    every: int = Field(..., ge=1)
    unit: Literal["minute", "hour", "day"]


class Weekly(_Input):
    days: list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]] = Field(..., min_length=1)


class Monthly(_Input):
    days: list[Annotated[int, Field(ge=1, le=31)]] = Field(..., min_length=1)


class Cadence(_Input):
    daily: dict | None = None
    weekly: Weekly | None = None
    monthly: Monthly | None = None

    @model_validator(mode="after")
    def exactly_one(self):
        if sum(v is not None for v in (self.daily, self.weekly, self.monthly)) != 1:
            raise ValueError("Choose exactly one daily, weekly or monthly cadence")
        if self.daily:
            raise ValueError("Daily cadence has no settings; use an empty object")
        return self


class Calendar(_Input):
    times_of_day: list[Annotated[str, Field(pattern=r"^([01][0-9]|2[0-3]):00$")]] = Field(..., min_length=1)
    cadence: Cadence


class Schedule(_Input):
    at: str | None = Field(None, description="Local timestamp without Z or offset; timezone is required.")
    rate: Rate | None = None
    calendar: Calendar | None = None
    timezone: str | None = None

    @model_validator(mode="after")
    def schedule_valid(self):
        if sum(v is not None for v in (self.at, self.rate, self.calendar)) != 1:
            raise ValueError("Choose exactly one at, rate or calendar schedule")
        if self.at is not None:
            try:
                parsed = datetime.fromisoformat(self.at)
                if parsed.tzinfo is not None or "T" not in self.at:
                    raise ValueError()
            except ValueError:
                raise ValueError("Use a local date and time without a timezone offset") from None
        if self.at is not None or self.calendar is not None:
            try:
                ZoneInfo(self.timezone or "")
            except (ValueError, ZoneInfoNotFoundError):
                raise ValueError("Supply an IANA timezone for a wall-clock schedule") from None
        return self


class _Job(_Input):
    job_id: ULID


class _Run(_Job):
    run_id: ULID


class _Page(_Input):
    cursor: str | None = Field(None, description="Echo the previous response's next_cursor; omit for the first page.")


class _Limited(_Page):
    limit: int = Field(50, ge=1, le=100)


class _Idempotency(_Input):
    idempotency_key: str | None = Field(None, min_length=1, max_length=128, pattern=r"^[\x21-\x7e]+$", description="Optional retry key. Same key and body replays the original response for 24 hours; inspect failures before retrying.")


class SubmitJob(_Idempotency):
    """Submit tasks for scraping; closed jobs need tasks or an uploaded file input."""
    operation: Literal["submit_job"] = "submit_job"
    type: Literal["regular", "scheduled"] = "regular"
    status: Literal["open", "closed"] = "closed"
    tasks: list[Task] | None = Field(None, max_length=100000)
    file_input_id: str | None = None
    zenrows_params: ScraperParams | None = None
    schedule: Schedule | None = None
    external_id: ExternalID | None = None
    name: str | None = Field(None, max_length=100)
    metadata: Metadata | None = None
    webhook: Webhook | None = None

    @model_validator(mode="after")
    def submission_valid(self):
        if self.tasks is not None and self.file_input_id is not None:
            raise ValueError("Use tasks or file_input_id, never both")
        if self.status == "closed" and not self.tasks and not self.file_input_id:
            raise ValueError("Closed jobs need tasks or file_input_id")
        if self.type == "scheduled" and (self.schedule is None or self.status != "closed"):
            raise ValueError("Scheduled jobs require a schedule and closed status")
        if self.status == "open" and self.file_input_id is not None:
            raise ValueError("Open jobs cannot use file_input_id")
        return self


class ListJobs(_Limited):
    operation: Literal["list_jobs"] = "list_jobs"
    status: Literal["open", "closed", "deleted"] | None = None
    type: Literal["regular", "scheduled"] | None = None


class GetJob(_Job):
    operation: Literal["get_job"] = "get_job"


class DeleteJob(_Job):
    """Request asynchronous deletion of a job and its artifacts."""
    operation: Literal["delete_job"] = "delete_job"


class AddTasks(_Job, _Idempotency):
    operation: Literal["add_tasks"] = "add_tasks"
    tasks: list[Task] = Field(..., min_length=1, max_length=10000)
    last_batch: StrictBool = False


class CloseJob(_Job):
    """Stop accepting tasks; tasks already queued continue running."""
    operation: Literal["close_job"] = "close_job"


class StopJob(_Job):
    """Stop the current run; retain stored results. In-flight tasks may finish."""
    operation: Literal["stop_job"] = "stop_job"


class CancelJob(_Job):
    operation: Literal["cancel_job"] = "cancel_job"


class PauseJob(_Job):
    operation: Literal["pause_job"] = "pause_job"


class ResumeJob(_Job):
    operation: Literal["resume_job"] = "resume_job"


class RerunJob(_Job, _Idempotency):
    """Start a new run; omit status for full replay or select task states to retry."""
    operation: Literal["rerun_job"] = "rerun_job"
    status: str | None = Field(None, pattern=r"^(pending|processing|failed|successful)(,(pending|processing|failed|successful))*$")


class UpdateJobSchedule(_Job):
    operation: Literal["update_job_schedule"] = "update_job_schedule"
    schedule: Schedule


class UpdateScheduleState(_Job):
    operation: Literal["update_schedule_state"] = "update_schedule_state"
    schedule_state: Literal["active", "paused"]


class GetJobWebhook(_Job):
    operation: Literal["get_job_webhook"] = "get_job_webhook"


class PutJobWebhook(_Job):
    operation: Literal["put_job_webhook"] = "put_job_webhook"
    webhook: Webhook


class DeleteJobWebhook(_Job):
    operation: Literal["delete_job_webhook"] = "delete_job_webhook"


class ListJobRuns(_Job, _Limited):
    operation: Literal["list_job_runs"] = "list_job_runs"


class GetJobRun(_Run):
    operation: Literal["get_job_run"] = "get_job_run"


class DeleteJobRun(_Run):
    """Request asynchronous deletion of this run and its stored results."""
    operation: Literal["delete_job_run"] = "delete_job_run"


class _Results(_Page):
    status: Literal["all", "successful", "failed", "processing"] = "all"


class ListLatestRunResults(_Job, _Results):
    operation: Literal["list_latest_run_results"] = "list_latest_run_results"


class ListRunResults(_Run, _Results):
    operation: Literal["list_run_results"] = "list_run_results"


class GetLatestRunTaskHistory(_Job):
    operation: Literal["get_latest_run_task_history"] = "get_latest_run_task_history"
    task_id: TaskID


class GetRunTaskHistory(_Run):
    operation: Literal["get_run_task_history"] = "get_run_task_history"
    task_id: TaskID


# ZenRows's own MCP server: agents get its tools through a person's ZenRows sign-in.
ZenrowsMcpCredential = mcp_credential("zenrows", "https://mcp.zenrows.com/mcp", app="ZenRows")
ZenrowsCredential = Union[ZenrowsAPIKeyCredential, ZenrowsMcpCredential]


ZenrowsConfig = Annotated[Union[SubmitJob, ListJobs, GetJob, DeleteJob, AddTasks, CloseJob, StopJob, CancelJob, PauseJob, ResumeJob, RerunJob, UpdateJobSchedule, UpdateScheduleState, GetJobWebhook, PutJobWebhook, DeleteJobWebhook, ListJobRuns, GetJobRun, DeleteJobRun, ListLatestRunResults, ListRunResults, GetLatestRunTaskHistory, GetRunTaskHistory], Field(discriminator="operation")]


class ZenrowsFullConfig(NodeConfig[ZenrowsConfig, ZenrowsCredential]):
    pass


# Each entry maps to exactly one operationId in the published contract.
ROUTES = {
    "submit_job": ("POST", "/jobs", (201, 202)),
    "list_jobs": ("GET", "/jobs", (200,)),
    "get_job": ("GET", "/jobs/{job_id}", (200,)),
    "delete_job": ("DELETE", "/jobs/{job_id}", (202,)),
    "add_tasks": ("POST", "/jobs/{job_id}/tasks", (200,)),
    "close_job": ("POST", "/jobs/{job_id}/close", (200,)),
    "stop_job": ("POST", "/jobs/{job_id}/stop", (200,)),
    "cancel_job": ("POST", "/jobs/{job_id}/cancel", (200,)),
    "pause_job": ("POST", "/jobs/{job_id}/pause", (200,)),
    "resume_job": ("POST", "/jobs/{job_id}/resume", (200,)),
    "rerun_job": ("POST", "/jobs/{job_id}/rerun", (201, 202)),
    "update_job_schedule": ("PUT", "/jobs/{job_id}/schedule", (200,)),
    "update_schedule_state": ("POST", "/jobs/{job_id}/schedule/state", (200,)),
    "get_job_webhook": ("GET", "/jobs/{job_id}/webhook", (200,)),
    "put_job_webhook": ("PUT", "/jobs/{job_id}/webhook", (200,)),
    "delete_job_webhook": ("DELETE", "/jobs/{job_id}/webhook", (204,)),
    "list_job_runs": ("GET", "/jobs/{job_id}/runs", (200,)),
    "get_job_run": ("GET", "/jobs/{job_id}/runs/{run_id}", (200,)),
    "delete_job_run": ("DELETE", "/jobs/{job_id}/runs/{run_id}", (202,)),
    "list_latest_run_results": ("GET", "/jobs/{job_id}/results", (200,)),
    "list_run_results": ("GET", "/jobs/{job_id}/runs/{run_id}/results", (200,)),
    "get_latest_run_task_history": ("GET", "/jobs/{job_id}/tasks/{task_id}/history", (200,)),
    "get_run_task_history": ("GET", "/jobs/{job_id}/runs/{run_id}/tasks/{task_id}/history", (200,)),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class ZenrowsNode(WorkflowNode):
    integration_type = "automation-zenrows"
    credential_provider_labels = {"zenrows": "ZenRows Account"}
    connection_evidence = ConnectionEvidence(noun="scraping jobs", operation="list_jobs", label_keys=("name", "external_id", "job_id"))

    @classmethod
    def get_config_model(cls):
        return ZenrowsFullConfig

    @staticmethod
    def _credential_family(config_data):
        raw = config_data.get("credentials")
        if isinstance(raw, dict) and raw.get("credential_type", "zenrows_api_key") != "zenrows_api_key":
            raise ValueError("Attach a ZenRows API key credential")

    @classmethod
    def parse_config(cls, config_data):
        cls._credential_family(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._credential_family(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        op, credential = self.config.config, self.config.credentials
        if credential is None:
            raise ValueError("Attach a ZenRows API key")
        values = op.model_dump(exclude_none=True, mode="json")
        method, path, success_codes = ROUTES[op.operation]
        for key in ("job_id", "run_id", "task_id"):
            if key in values:
                path = path.replace("{" + key + "}", quote(values.pop(key), safe=""))
        values.pop("operation")
        headers = {"X-API-Key": credential.api_key, "Accept": "application/json"}
        key = values.pop("idempotency_key", None)
        if key is not None:
            headers["Idempotency-Key"] = key
        params, body = {}, None
        if method == "GET" or op.operation == "rerun_job":
            params = values
        elif op.operation in {"submit_job", "add_tasks", "update_schedule_state"}:
            body = values
        elif op.operation == "update_job_schedule":
            body = values["schedule"]
        elif op.operation == "put_job_webhook":
            body = values["webhook"]
        try:
            async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, headers=headers, params=params, **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            return {"status": "error", "error": "ZenRows request did not complete; inspect the job before retrying writes."}
        if response.status_code not in success_codes:
            message = "ZenRows returned an unexpected response"
            try:
                problem = response.json()
                if isinstance(problem, dict):
                    message = problem.get("detail") or problem.get("title") or message
            except ValueError:
                pass
            return {"status": "error", "status_code": response.status_code, "error": _redact(str(message), credential.api_key)}
        if op.operation in {"delete_job", "delete_job_run", "delete_job_webhook"}:
            return {"status": "success", "status_code": response.status_code, "accepted": True, "deletion_complete": op.operation == "delete_job_webhook"}
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Expected a JSON object from ZenRows") from None
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object from ZenRows")
        list_key = {"list_jobs": "jobs", "list_job_runs": "runs", "list_latest_run_results": "results", "list_run_results": "results", "get_latest_run_task_history": "events", "get_run_task_history": "events"}.get(op.operation)
        if list_key and (not isinstance(payload.get(list_key), list) or any(not isinstance(row, dict) for row in payload[list_key])):
            raise ValueError("ZenRows returned an invalid list envelope")
        result = {"status": "success", "status_code": response.status_code, "data": payload}
        if list_key:
            result["items"] = payload[list_key]
        return _redact(result, credential.api_key)
