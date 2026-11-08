"""Visualping's published v2 job and account API with a pasted API key.

Each action makes one documented request. Focused job actions only change the
selected fields; list results expose page continuation without hiding limits.
Contract: https://api.visualping.io/data/openapi-definition.yaml (2.4.0).
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

ACCOUNT_URL = "https://account.api.visualping.io"
JOB_URL = "https://job.api.visualping.io"


class VisualpingAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Visualping API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://visualping.io/account/developer",
            "x-credential-instructions": "Create an API key in Visualping's Developer settings and paste it here. NoClick sends it as a Bearer token to Visualping's account and job APIs. Business accounts must select a workspace for job operations.",
        })
    credential_type: Literal["visualping_api_key"] = Field("visualping_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def valid_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class DescribeUser(_Input):
    """Read the authenticated profile, organisation and workspace memberships."""
    operation: Literal["describe_user"] = "describe_user"


class ListWorkspaces(_Input):
    """List your workspace names and IDs using the authenticated account API."""
    operation: Literal["list_workspaces"] = "list_workspaces"


class _Workspace(_Input):
    workspace_id: int | None = Field(None, ge=1, description="Required for business accounts. Find it with List Workspaces.")


class ListJobs(_Workspace):
    """Read one page of monitors with optional activity, text and event filters."""
    operation: Literal["list_jobs"] = "list_jobs"
    page_index: int = Field(0, ge=0, description="Zero-based page. Use next_page_index from the previous result.")
    page_size: int = Field(100, ge=1, le=100, description="Maximum jobs on this page.")
    search: str | None = Field(None, max_length=2000, description="Substring of job URL or description.")
    active: bool | None = Field(None, description="Filter active or paused jobs; omit to include both.")
    event: Literal["changed", "changedImportant", "errored", "checked"] | None = None
    date_filter: Literal["since_last_login", "since_yesterday", "since_last_week", "since_last_month", "since_custom_date"] | None = None
    date_filter_start: str | None = Field(None, description="ISO date/time, required for since_custom_date.")

    @model_validator(mode="after")
    def custom_date(self):
        if self.date_filter == "since_custom_date" and not self.date_filter_start:
            raise ValueError("Supply date_filter_start for a custom date filter")
        return self


class SearchJobs(ListJobs):
    """Find monitors by a substring in their URL or description."""
    operation: Literal["search_jobs"] = "search_jobs"
    search: str = Field(..., min_length=1, max_length=2000)


class ListChangedJobs(ListJobs):
    """Find jobs with changes since yesterday, or another selected interval."""
    operation: Literal["list_changed_jobs"] = "list_changed_jobs"
    event: Literal["changed", "changedImportant"] = "changed"
    date_filter: Literal["since_last_login", "since_yesterday", "since_last_week", "since_last_month", "since_custom_date"] = "since_yesterday"


class ListPausedJobs(ListJobs):
    """Read one page of paused monitors."""
    operation: Literal["list_paused_jobs"] = "list_paused_jobs"
    active: Literal[False] = False


class CountJobs(_Workspace):
    """Read total and active monitor counts without requesting job records."""
    operation: Literal["count_jobs"] = "count_jobs"


class _Job(_Workspace):
    job_id: int = Field(..., ge=1, description="Visualping job ID.")


class GetJob(_Job):
    """Get a monitor's details, history and detected changes."""
    operation: Literal["get_job"] = "get_job"


class GetJobHistory(_Job):
    """Read a monitor's available check history and detected changes."""
    operation: Literal["get_job_history"] = "get_job_history"


class _JobFields(_Workspace):
    url: str | None = Field(None, max_length=2000)
    description: str | None = None
    mode: Literal["VISUAL", "WEB", "TEXT", "ALL"] | None = None
    active: bool | None = None
    interval: str | None = Field(None, pattern=r"^[1-9][0-9]*$", description="Check interval in minutes, sent as a string.")
    trigger: str | None = Field(None, pattern=r"^(?:[0-9]+)(?:\.[0-9]+)?$", description="Change threshold in percent, sent as a string.")
    target_device: Literal["1", "2", "3", "4"] | None = None
    wait_time: int | None = Field(None, ge=0)
    xpath: str | None = None
    keywords: str | None = None
    keyword_action: Literal["ALL", "ADDED", "DELETED"] | None = None
    label_ids: list[int] | None = None

    @field_validator("url")
    @classmethod
    def valid_url(cls, value):
        if value is not None:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Use an HTTP or HTTPS page URL without credentials")
        return value


class CreateJob(_JobFields):
    """Create a monitor with the required v2 fields and daily checking by default."""
    operation: Literal["create_job"] = "create_job"
    url: str = Field(..., min_length=1, max_length=2000)
    mode: Literal["VISUAL", "WEB", "TEXT", "ALL"] = "ALL"
    active: bool = True
    interval: str = Field("1440", pattern=r"^[1-9][0-9]*$")
    trigger: str = Field("1", pattern=r"^(?:[0-9]+)(?:\.[0-9]+)?$")
    target_device: Literal["1", "2", "3", "4"] = "4"
    wait_time: int = Field(0, ge=0)


class UpdateJob(_JobFields):
    """Update only the supplied monitor fields; omitted values are unchanged."""
    operation: Literal["update_job"] = "update_job"
    job_id: int = Field(..., ge=1)
    organisation_id: int | None = Field(None, ge=1, description="Required for business updates by the published request schema.")

    @model_validator(mode="after")
    def has_changes(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "job_id", "workspace_id", "organisation_id"}):
            raise ValueError("Supply at least one field to update")
        return self


class _UpdateTarget(_Job):
    organisation_id: int | None = Field(None, ge=1, description="Required for business updates by the published request schema.")


class PauseJob(_UpdateTarget):
    """Pause a monitor by setting active to false."""
    operation: Literal["pause_job"] = "pause_job"


class ResumeJob(_UpdateTarget):
    """Resume a monitor by setting active to true."""
    operation: Literal["resume_job"] = "resume_job"


class SetJobFrequency(_UpdateTarget):
    """Change a monitor's check interval in minutes."""
    operation: Literal["set_job_frequency"] = "set_job_frequency"
    interval: str = Field(..., pattern=r"^[1-9][0-9]*$")


class SetJobKeywords(_UpdateTarget):
    """Set comma-separated keywords and their change filter on a text monitor."""
    operation: Literal["set_job_keywords"] = "set_job_keywords"
    keywords: str = Field(..., min_length=1)
    keyword_action: Literal["ALL", "ADDED", "DELETED"] = "ALL"


class SetJobLabels(_UpdateTarget):
    """Replace a monitor's label IDs; an empty list clears them."""
    operation: Literal["set_job_labels"] = "set_job_labels"
    label_ids: list[int] = Field(..., description="Existing label IDs. Use [] to clear labels.")


class DeleteJob(_Job):
    """Delete one monitor and report the provider's deletion acknowledgement."""
    operation: Literal["delete_job"] = "delete_job"


VisualpingConfig = Annotated[Union[DescribeUser, ListWorkspaces, ListJobs, SearchJobs,
    ListChangedJobs, ListPausedJobs, CountJobs, GetJob, GetJobHistory, CreateJob,
    UpdateJob, PauseJob, ResumeJob, SetJobFrequency, SetJobKeywords, SetJobLabels,
    DeleteJob], Field(discriminator="operation")]


class VisualpingFullConfig(NodeConfig[VisualpingConfig, VisualpingAPIKeyCredential]):
    pass


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, key) for k, v in value.items()}
    return value


class VisualpingNode(WorkflowNode):
    integration_type = "automation-visualping"
    connection_evidence = ConnectionEvidence(noun="workspaces", operation="list_workspaces", identity_operation="describe_user")

    @classmethod
    def get_config_model(cls):
        return VisualpingFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Attach a Visualping API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, host, path = "GET", JOB_URL, "/v2/jobs"
        params, body = {}, None
        if isinstance(op, (DescribeUser, ListWorkspaces)):
            host, path = ACCOUNT_URL, "/describe-user"
        elif isinstance(op, (ListJobs, CountJobs)):
            if op.workspace_id is not None:
                params["workspaceId"] = op.workspace_id
            if isinstance(op, CountJobs):
                params["mode"] = "counts_only"
            else:
                params.update(mode="normal", pageIndex=op.page_index, pageSize=op.page_size)
                for field, wire in {"search": "fullTextSearchFilter", "event": "eventFilter", "date_filter": "dateFilter", "date_filter_start": "dateFilterStart"}.items():
                    if getattr(op, field) is not None:
                        params[wire] = getattr(op, field)
                if op.active is not None:
                    params["activeFilter"] = int(op.active)
        elif isinstance(op, CreateJob):
            method = "POST"
            body = op.model_dump(exclude={"operation"}, exclude_none=True)
        else:
            path += "/" + str(op.job_id)
            if isinstance(op, (GetJob, GetJobHistory, DeleteJob)):
                if op.workspace_id is not None:
                    params["workspaceId"] = op.workspace_id
                if isinstance(op, DeleteJob):
                    method = "DELETE"
            else:
                method = "PUT"
                body = op.model_dump(exclude={"operation", "job_id"}, exclude_none=True)
                if isinstance(op, (PauseJob, ResumeJob)):
                    body["active"] = isinstance(op, ResumeJob)
        if body is not None:
            for field, wire in {"workspace_id": "workspaceId", "organisation_id": "organisationId", "label_ids": "labelIds"}.items():
                if field in body:
                    body[wire] = body.pop(field)
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, host + path, params=params,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
            if response.status_code != 200:
                message = response.text[:2000]
                return {"status": "error", "operation": op.operation, "http_status": response.status_code,
                    "error": _redact(message or "Visualping did not confirm the request", key)}
            data = response.json()
            if not isinstance(data, dict) or data.get("error") or data.get("errors"):
                raise ValueError("Visualping returned an error or invalid JSON object")
            result = {"status": "success", "operation": op.operation, "data": data}
            if isinstance(op, (DescribeUser, ListWorkspaces)):
                if not isinstance(data.get("workspaces"), list) or not isinstance(data.get("emailAddress"), str) or type(data.get("userId")) is not int:
                    raise ValueError("Visualping returned an incomplete account response")
                result.update(email=data["emailAddress"], user_id=data["userId"])
                if isinstance(op, ListWorkspaces):
                    result["items"] = [{k: row[k] for k in ("id", "name", "role", "timeZone") if k in row} for row in data["workspaces"]]
                    del result["data"]
            elif isinstance(op, (ListJobs, CountJobs)):
                if any(type(data.get(k)) is not int for k in ("totalJobs", "activeJobCount", "totalPages", "pageSize")):
                    raise ValueError("Visualping returned incomplete page counts")
                if isinstance(op, ListJobs):
                    if not isinstance(data.get("jobs"), list):
                        raise ValueError("Visualping omitted jobs in normal mode")
                    result.update(items=data["jobs"], next_page_index=op.page_index + 1 if op.page_index + 1 < data["totalPages"] else None)
            elif isinstance(op, (GetJob, GetJobHistory)):
                if not isinstance(data.get("id"), str) or data["id"] != str(op.job_id):
                    raise ValueError("Visualping returned a different job ID")
                if isinstance(op, GetJobHistory):
                    if not isinstance(data.get("history"), list) or not isinstance(data.get("changes"), list):
                        raise ValueError("Visualping omitted job history or changes")
                    result["data"] = {k: data[k] for k in ("id", "history", "changes")}
            elif isinstance(op, CreateJob):
                if not isinstance(data.get("jobid"), str) or not data["jobid"]:
                    raise ValueError("Visualping omitted the created job ID")
                result.update(job_id=data["jobid"], write_acknowledged=True)
            elif isinstance(op, DeleteJob):
                if type(data.get("changed")) is not bool:
                    raise ValueError("Visualping omitted the deletion acknowledgement")
                result["write_acknowledged"] = data["changed"]
            else:
                if data.get("updates") not in {"none", "non-breaking-only", "preview-breaking", "render-breaking"}:
                    raise ValueError("Visualping omitted the update impact")
                result["write_acknowledged"] = True
            return _redact(result, key)
        except (ValueError, httpx.HTTPError, SSRFError):
            return {"status": "error", "operation": op.operation,
                "error": "Visualping request could not be confirmed. Check the account and job before retrying a write."}
