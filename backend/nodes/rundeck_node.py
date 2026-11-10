"""Rundeck API v60: token-authenticated job and execution automation.

Contract: https://docs.rundeck.com/docs/files/rundeck-api.yml
Rundeck webhooks receive events; completion notifications use the documented
execution query time filter instead. No credentials or live account are bundled.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client


class RundeckTokenCredential(BaseModel):
    model_config = ConfigDict(title="Rundeck API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.rundeck.com/docs/api/#api-token-authentication",
            "x-credential-instructions": "Paste an existing API token from your Rundeck User Profile and the public HTTPS server URL. Use a token whose roles allow the selected jobs and projects. NoClick sends X-Rundeck-Auth-Token over HTTPS and checks your user profile. API version 60 is required.",
        })
    credential_type: Literal["rundeck_api_token"] = Field("rundeck_api_token", json_schema_extra={"ui:hidden": True})
    server_url: str = Field(..., title="Server URL", description="Your public HTTPS Rundeck server, for example https://rundeck.example.com. Include a deployment context path if used; omit /api/60.")
    api_token: str = Field(..., title="API Token", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("server_url")
    @classmethod
    def server(cls, value):
        value = value.strip().rstrip("/")
        try:
            p = urlsplit(value)
            if (p.scheme != "https" or not p.hostname or p.username is not None
                    or p.password is not None or p.query or p.fragment
                    or p.port == 0 or any(c.isspace() for c in value)
                    or not value.isascii() or "\\" in value
                    or any(s in {".", ".."} for s in p.path.split("/"))
                    or "%" in p.path or re.search(r"/api(?:/|$)", p.path)):
                raise ValueError()
        except ValueError:
            raise ValueError("Use the public HTTPS server URL without credentials, query, fragment, or /api/version") from None
        return value

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token", key=True)
        if not value or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a header prefix or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


def _segment(value):
    if value in {".", ".."} or any(c in "/\\" or ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Use a single resource name or ID without path separators")
    return value


class ProjectInput(Input):
    project: str = Field(..., min_length=1, max_length=255, title="Project Name")
    _project = field_validator("project")(_segment)


class JobInput(Input):
    job_id: str = Field(..., min_length=1, max_length=255, title="Job ID")
    _job = field_validator("job_id")(_segment)


class ExecutionInput(Input):
    execution_id: str = Field(..., min_length=1, max_length=255, title="Execution ID")
    _execution = field_validator("execution_id")(_segment)


class Page(Input):
    max: int = Field(100, ge=1, le=1000, title="Page Size")
    offset: int = Field(0, ge=0, title="Offset", description="Request another page explicitly using the next offset. Results are one page only.")


class RunOptions(Input):
    arg_string: str | None = Field(None, title="Arguments", description="Job options in Rundeck format, for example -opt value.")
    options: dict[str, str] | None = Field(None, title="Option Values", description="Option name to value map. When supplied, Rundeck ignores Arguments.")
    loglevel: Literal["DEBUG", "VERBOSE", "INFO", "WARN", "ERROR"] | None = Field(None, title="Log Level")
    node_filter: str | None = Field(None, title="Node Filter")


class GetProfileConfig(Input):
    operation: Literal["get_profile"] = Field("get_profile", title="Get My Profile", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class ListProjectsConfig(Input):
    operation: Literal["list_projects"] = Field("list_projects", title="List Projects", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class GetProjectConfig(ProjectInput):
    operation: Literal["get_project"] = Field("get_project", title="Get Project", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class ListJobsConfig(ProjectInput, Page):
    operation: Literal["list_jobs"] = Field("list_jobs", title="List Jobs", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    job_filter: str | None = Field(None, title="Job Name Contains")
    group_path: str | None = Field(None, title="Group Path")


class GetJobConfig(JobInput):
    operation: Literal["get_job"] = Field("get_job", title="Get Job Metadata", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class GetJobWorkflowConfig(JobInput):
    operation: Literal["get_job_workflow"] = Field("get_job_workflow", title="Get Job Workflow", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class RunJobConfig(JobInput, RunOptions):
    operation: Literal["run_job"] = Field("run_job", title="Run Job", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class RetryJobConfig(JobInput, RunOptions):
    operation: Literal["retry_job"] = Field("retry_job", title="Retry Job Execution", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    execution_id: str = Field(..., min_length=1, max_length=255, title="Execution ID")
    _execution = field_validator("execution_id")(_segment)
    failed_nodes: bool = Field(False, title="Retry Failed Nodes Only")


class EnableJobExecutionConfig(JobInput):
    operation: Literal["enable_job_execution"] = Field("enable_job_execution", title="Enable Job Execution", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class DisableJobExecutionConfig(JobInput):
    operation: Literal["disable_job_execution"] = Field("disable_job_execution", title="Disable Job Execution", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class EnableJobScheduleConfig(JobInput):
    operation: Literal["enable_job_schedule"] = Field("enable_job_schedule", title="Enable Job Schedule", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class DisableJobScheduleConfig(JobInput):
    operation: Literal["disable_job_schedule"] = Field("disable_job_schedule", title="Disable Job Schedule", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class ListJobExecutionsConfig(JobInput, Page):
    operation: Literal["list_job_executions"] = Field("list_job_executions", title="List Job Executions", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    status: Literal["succeeded", "failed", "aborted", "running"] | None = Field(None, title="Execution Status")


class GetExecutionConfig(ExecutionInput):
    operation: Literal["get_execution"] = Field("get_execution", title="Get Execution", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class GetExecutionStateConfig(ExecutionInput):
    operation: Literal["get_execution_state"] = Field("get_execution_state", title="Get Execution State", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class GetExecutionOutputConfig(ExecutionInput):
    operation: Literal["get_execution_output"] = Field("get_execution_output", title="Get Execution Output", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    offset: int = Field(0, ge=0, title="Log Byte Offset")
    maxlines: int = Field(100, ge=1, le=10000, title="Maximum Lines")


class AbortExecutionConfig(ExecutionInput):
    operation: Literal["abort_execution"] = Field("abort_execution", title="Abort Execution", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    force_incomplete: bool = Field(False, title="Force Incomplete", description="Force a running execution to be marked incomplete.")


class QueryExecutionsConfig(ProjectInput, Page):
    operation: Literal["query_executions"] = Field("query_executions", title="Query Executions", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    status_filter: Literal["running", "succeeded", "failed", "aborted"] | None = Field(None, title="Execution Status")
    recent_filter: str | None = Field(None, title="Completed Within", pattern=r"^[1-9][0-9]*[snhdwmy]$", description="Relative completion window, for example 2w.")
    begin: str | None = Field(None, title="Completed After", description="Unix millisecond timestamp or W3C dateTime.")
    end: str | None = Field(None, title="Completed Before", description="Unix millisecond timestamp or W3C dateTime.")
    job_id_filter: str | None = Field(None, title="Job ID Filter")


class ListRunningExecutionsConfig(ProjectInput, Page):
    operation: Literal["list_running_executions"] = Field("list_running_executions", title="List Running Executions", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class ListNodesConfig(ProjectInput):
    operation: Literal["list_nodes"] = Field("list_nodes", title="List Project Nodes", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    node_filter: str | None = Field(None, title="Node Filter")


class OnCompletedExecutionConfig(PollTriggerConfigBase):
    operation: Literal["on_completed_execution"] = Field("on_completed_execution", title="On New Completed Execution", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    project: str = Field(..., title="Project Name", min_length=1, max_length=255)
    _project = field_validator("project")(_segment)
    recent_filter: str = Field("2w", title="Completion Window", pattern=r"^[1-9][0-9]*[snhdwmy]$", description="Poll executions completed in this relative window. Keep it longer than the polling interval and expected outages, e.g. 2w. Baselines existing executions on first poll.")
    status_filter: Literal["succeeded", "failed", "aborted"] | None = Field(None, title="Completion Status", description="Leave empty to watch every completed status.")
    job_id_filter: str | None = Field(None, title="Job ID Filter")


RundeckOperation = Annotated[Union[GetProfileConfig, ListProjectsConfig, GetProjectConfig, ListJobsConfig, GetJobConfig, GetJobWorkflowConfig, RunJobConfig, RetryJobConfig, EnableJobExecutionConfig, DisableJobExecutionConfig, EnableJobScheduleConfig, DisableJobScheduleConfig, ListJobExecutionsConfig, GetExecutionConfig, GetExecutionStateConfig, GetExecutionOutputConfig, AbortExecutionConfig, QueryExecutionsConfig, ListRunningExecutionsConfig, ListNodesConfig, OnCompletedExecutionConfig], Field(discriminator="operation")]


class RundeckNodeConfig(NodeConfig[RundeckOperation, RundeckTokenCredential]):
    pass


# Exactly one API operation per action; names follow the pinned v60 contract.
ROUTES = {
    "get_profile": ("GET", "/user/info"),
    "list_projects": ("GET", "/projects"),
    "get_project": ("GET", "/project/{project}"),
    "list_jobs": ("GET", "/project/{project}/jobs"),
    "get_job": ("GET", "/job/{id}/info"),
    "get_job_workflow": ("GET", "/job/{id}/workflow"),
    "run_job": ("POST", "/job/{id}/run"),
    "retry_job": ("POST", "/job/{id}/retry/{executionId}"),
    "enable_job_execution": ("POST", "/job/{id}/execution/enable"),
    "disable_job_execution": ("POST", "/job/{id}/execution/disable"),
    "enable_job_schedule": ("POST", "/job/{id}/schedule/enable"),
    "disable_job_schedule": ("POST", "/job/{id}/schedule/disable"),
    "list_job_executions": ("GET", "/job/{id}/executions"),
    "get_execution": ("GET", "/execution/{id}"),
    "get_execution_state": ("GET", "/execution/{id}/state"),
    "get_execution_output": ("GET", "/execution/{id}/output"),
    "abort_execution": ("POST", "/execution/{id}/abort"),
    "query_executions": ("GET", "/project/{project}/executions"),
    "list_running_executions": ("GET", "/project/{project}/executions/running"),
    "list_nodes": ("GET", "/project/{project}/resources"),
}
QUERY_FIELDS = {
    "max": "max", "offset": "offset", "job_filter": "jobFilter",
    "group_path": "groupPath", "status": "status", "node_filter": "filter",
    "status_filter": "statusFilter", "recent_filter": "recentFilter",
    "begin": "begin", "end": "end", "job_id_filter": "jobIdListFilter",
    "maxlines": "maxlines", "force_incomplete": "forceIncomplete",
}
BODY_FIELDS = {"arg_string": "argString", "options": "options", "loglevel": "loglevel", "node_filter": "filter", "failed_nodes": "failedNodes"}


class RundeckNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-rundeck"
    connection_evidence = ConnectionEvidence(noun="Rundeck user profile", identity_operation="get_profile", identity_keys=("login", "email"))

    @classmethod
    def get_config_model(cls):
        return RundeckNodeConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        async with guarded_async_client(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, credential.server_url + "/api/60" + path,
                headers={"X-Rundeck-Auth-Token": credential.api_token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if response.status_code >= 300:
            # Keep a definitive auth rejection available to the connect seam.
            error = "Rundeck request failed"
            try:
                payload = response.json()
                if isinstance(payload, dict) and isinstance(payload.get("message"), str):
                    error = payload["message"].replace(credential.api_token, "[redacted]")[:1000]
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": error}
        if response.status_code == 204:
            return {"status": "success", "data": None}
        if len(response.content) > 10_000_000:
            raise ValueError("Rundeck response is too large; request a smaller page")
        if response.headers.get("Content-Type", "").split(";")[0].lower() != "application/json":
            raise ValueError("Expected Rundeck JSON; check the server URL")
        data = response.json()
        if isinstance(data, dict) and data.get("error") is True:
            return {"status": "error", "error": str(data.get("message", "Rundeck rejected the request")).replace(credential.api_token, "[redacted]")[:1000]}
        return {"status": "success", "data": data}

    async def _poll_completed(self, config):
        # Query only completed executions. Scan the whole bounded window before
        # dedup so a full first page cannot silently hide new completions.
        items = []
        offset = 0
        for _ in range(100):
            params = {"recentFilter": config.recent_filter, "max": 100, "offset": offset}
            if config.status_filter is not None:
                params["statusFilter"] = config.status_filter
            if config.job_id_filter is not None:
                params["jobIdListFilter"] = config.job_id_filter
            result = await self._request("GET", "/project/" + quote(config.project, safe="") + "/executions", params=params)
            if result["status"] != "success":
                return result
            data = result["data"]
            if not isinstance(data, dict) or not isinstance(data.get("executions"), list) or not isinstance(data.get("paging"), dict):
                raise ValueError("Rundeck execution query is missing executions or paging")
            rows, paging = data["executions"], data["paging"]
            if any(not isinstance(row, dict) or not isinstance(row.get("id"), (str, int)) for row in rows):
                raise ValueError("Rundeck execution is missing its ID")
            items.extend(rows)
            total = paging.get("total")
            if type(total) is not int or total < 0:
                raise ValueError("Rundeck execution paging is missing total")
            count = paging.get("count")
            if type(count) is not int or count < len(rows):
                raise ValueError("Rundeck execution paging has an invalid count")
            offset += count
            if offset >= total:
                break
            if not rows:
                raise ValueError("Rundeck execution paging did not advance")
        else:
            raise ValueError("More than 10000 completions in the window; narrow the window or select a job")
        fresh = await self._filter_unseen(items, lambda item: str(item["id"]))
        return {"status": "success", "executions": fresh, "new_execution_count": len(fresh)}

    async def execute(self, inputs):
        if not isinstance(self.config, RundeckNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a Rundeck API token")
        config = self.config.config
        if isinstance(config, OnCompletedExecutionConfig):
            return await self._poll_completed(config)
        method, path = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for key, wire in (("project", "project"), ("job_id", "id"), ("execution_id", "executionId" if config.operation == "retry_job" else "id")):
            if key in values:
                path = path.replace("{" + wire + "}", quote(str(values.pop(key)), safe=""))
        if config.operation in {"run_job", "retry_job"}:
            return await self._request(method, path, body={BODY_FIELDS[k]: v for k, v in values.items()})
        return await self._request(method, path, params={QUERY_FIELDS[k]: v for k, v in values.items()})
