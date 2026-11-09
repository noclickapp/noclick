"""Kadoa workflow and extraction-schema API (OpenAPI version 3.0.0).

Each operation sends one request. Run/resume acknowledgments do not establish
that extraction has finished; inspect run history or job status afterwards.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.kadoa.com"


class KadoaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Kadoa API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.kadoa.com/docs/api-keys",
            "x-credential-instructions": "An Admin or Owner can generate a team API key in Kadoa Settings > General. Paste it here. NoClick sends it in the x-api-key header to api.kadoa.com. Listing your workflows verifies read access; individual writes may need additional permissions.",
        })
    credential_type: Literal["kadoa_api_key"] = Field("kadoa_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


ResourceID = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]


class _Workflow(_Input):
    workflow_id: ResourceID = Field(..., title="Workflow ID")


class ListWorkflows(_Input):
    """List one page of workflows; advance skip by the returned page size."""
    operation: Literal["list_workflows"] = "list_workflows"
    skip: int = Field(0, ge=0)
    limit: int = Field(25, ge=1, le=1000)
    search: str | None = None
    state: Literal["ACTIVE", "DRAFT", "PAUSED", "PREVIEW", "QUEUED", "SETUP", "COMPLIANCE_REVIEW", "COMPLIANCE_REJECTED", "NOT_SUPPORTED", "ERROR", "DELETED"] | None = None


class GetWorkflow(_Workflow):
    operation: Literal["get_workflow"] = "get_workflow"


class CreateWorkflow(_Input):
    """Create a prompt-driven extraction workflow for a single website."""
    operation: Literal["create_workflow"] = "create_workflow"
    urls: list[str] = Field(..., min_length=1, description="Source URLs from one website, including its subdomains. Use a separate workflow for each website.")
    user_prompt: str = Field(..., min_length=10, max_length=5000)
    name: str | None = Field(None, min_length=1)
    description: str | None = Field(None, max_length=500)
    limit: int | None = Field(None, ge=1, le=2147483647)
    schema_id: ResourceID | None = None
    bypass_preview: bool = Field(False, description="Skip preview and deploy immediately. This can start paid extraction.")

    @field_validator("urls")
    @classmethod
    def urls_valid(cls, values):
        from urllib.parse import urlsplit
        for value in values:
            parts = urlsplit(value)
            if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password or any(c.isspace() for c in value):
                raise ValueError("Use absolute HTTP or HTTPS source URLs")
        return values


class DeleteWorkflow(_Workflow):
    """Delete the selected workflow."""
    operation: Literal["delete_workflow"] = "delete_workflow"


class GetWorkflowData(_Workflow):
    """Read a bounded JSON data page; pagination is returned by Kadoa."""
    operation: Literal["get_workflow_data"] = "get_workflow_data"
    page: int = Field(1, ge=1)
    limit: int = Field(25, ge=1, le=1000)
    run_id: ResourceID | None = None
    sort_by: str | None = None
    order: Literal["asc", "desc"] = "asc"
    filters: str | None = Field(None, description="JSON-encoded array of Kadoa filter objects.")

    @field_validator("filters")
    @classmethod
    def filters_valid(cls, value):
        if value is not None:
            import json
            parsed = json.loads(value)
            if not isinstance(parsed, list) or any(not isinstance(v, dict) for v in parsed):
                raise ValueError("Filters must be a JSON array of objects")
        return value


class GetWorkflowHistory(_Workflow):
    operation: Literal["get_workflow_history"] = "get_workflow_history"
    page: int = Field(1, ge=1)
    limit: int = Field(25, ge=1, le=1000)
    run_id: ResourceID | None = None
    status: Literal["success", "failed", "in_progress", "stopped"] | None = None


class GetJob(_Workflow):
    operation: Literal["get_job"] = "get_job"
    job_id: ResourceID


class UpdateWorkflowMetadata(_Workflow):
    """Update descriptive metadata without replacing extraction settings."""
    operation: Literal["update_workflow_metadata"] = "update_workflow_metadata"
    name: str = Field(..., min_length=1)
    description: str | None = None
    tags: list[str] | None = None


class PauseWorkflow(_Workflow):
    operation: Literal["pause_workflow"] = "pause_workflow"


class ResumeWorkflow(_Workflow):
    """Resume or approve the workflow. Kadoa may start a new preview run."""
    operation: Literal["resume_workflow"] = "resume_workflow"


class RunWorkflow(_Workflow):
    """Start extraction; the response acknowledges rather than finishes it."""
    operation: Literal["run_workflow"] = "run_workflow"
    variables: dict | None = None
    limit: float | None = Field(None, ge=1)
    preview: bool | None = None


class StopWorkflow(_Workflow):
    """Request stopping the active extraction run."""
    operation: Literal["stop_workflow"] = "stop_workflow"


class ScheduleWorkflow(_Workflow):
    operation: Literal["schedule_workflow"] = "schedule_workflow"
    date: str = Field(..., description="UTC ISO date, for example 2023-10-07T10:00:00.000Z.")

    @field_validator("date")
    @classmethod
    def utc_date(cls, value):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
                raise ValueError()
        except ValueError:
            raise ValueError("Provide a UTC ISO timestamp ending in Z or +00:00") from None
        return value


class ListWorkflowConnectors(_Workflow):
    operation: Literal["list_workflow_connectors"] = "list_workflow_connectors"


class GetWorkflowQualityMetrics(_Workflow):
    operation: Literal["get_workflow_quality_metrics"] = "get_workflow_quality_metrics"
    job_id: ResourceID | None = None


class DataField(_Input):
    name: str = Field(..., pattern=r"^[^.]*$")
    description: str = Field(..., min_length=1)
    fieldType: Literal["SCHEMA"] = "SCHEMA"
    dataType: Literal["STRING", "NUMBER", "BOOLEAN", "DATE", "DATETIME", "MONEY", "IMAGE", "LINK", "OBJECT", "ARRAY"]
    isKey: bool | None = None


class ListSchemas(_Input):
    operation: Literal["list_schemas"] = "list_schemas"


class GetSchema(_Input):
    operation: Literal["get_schema"] = "get_schema"
    schema_id: ResourceID


class CreateSchema(_Input):
    """Create a reusable schema with typed extraction fields."""
    operation: Literal["create_schema"] = "create_schema"
    name: str = Field(..., min_length=1, max_length=255)
    entity: str | None = Field(None, min_length=1)
    fields: list[DataField] = Field(..., min_length=1)


class UpdateSchema(_Input):
    """Rename a schema and optionally replace its extraction fields."""
    operation: Literal["update_schema"] = "update_schema"
    schema_id: ResourceID
    name: str = Field(..., min_length=1, max_length=255)
    entity: str | None = Field(None, min_length=1)
    fields: list[DataField] | None = None


class DeleteSchema(_Input):
    operation: Literal["delete_schema"] = "delete_schema"
    schema_id: ResourceID


KadoaOperation = Annotated[Union[
    ListWorkflows, GetWorkflow, CreateWorkflow, DeleteWorkflow, GetWorkflowData,
    GetWorkflowHistory, GetJob, UpdateWorkflowMetadata, PauseWorkflow,
    ResumeWorkflow, RunWorkflow, StopWorkflow, ScheduleWorkflow,
    ListWorkflowConnectors, GetWorkflowQualityMetrics, ListSchemas, GetSchema,
    CreateSchema, UpdateSchema, DeleteSchema,
], Field(discriminator="operation")]


class KadoaConfig(NodeConfig[KadoaOperation, KadoaAPIKeyCredential]):
    pass


# Published contract: https://api.kadoa.com/openapi, version 3.0.0.
ROUTES = {
    "list_workflows": ("GET", "/v6/workflows"),
    "get_workflow": ("GET", "/v6/workflows/{workflow_id}"),
    "create_workflow": ("POST", "/v6/workflows"),
    "delete_workflow": ("DELETE", "/v6/workflows/{workflow_id}"),
    "get_workflow_data": ("GET", "/v6/workflows/{workflow_id}/data"),
    "get_workflow_history": ("GET", "/v6/workflows/{workflow_id}/history"),
    "get_job": ("GET", "/v6/workflows/{workflow_id}/jobs/{job_id}"),
    "update_workflow_metadata": ("PUT", "/v6/workflows/{workflow_id}/metadata"),
    "pause_workflow": ("PUT", "/v6/workflows/{workflow_id}/pause"),
    "resume_workflow": ("PUT", "/v6/workflows/{workflow_id}/resume"),
    "run_workflow": ("PUT", "/v6/workflows/{workflow_id}/run"),
    "stop_workflow": ("PUT", "/v6/workflows/{workflow_id}/stop"),
    "schedule_workflow": ("PUT", "/v6/workflows/{workflow_id}/schedule"),
    "list_workflow_connectors": ("GET", "/v6/workflows/{workflow_id}/connectors"),
    "get_workflow_quality_metrics": ("GET", "/v6/workflows/{workflow_id}/quality-metrics"),
    "list_schemas": ("GET", "/v6/schemas/"),
    "get_schema": ("GET", "/v6/schemas/{schema_id}"),
    "create_schema": ("POST", "/v6/schemas/"),
    "update_schema": ("PUT", "/v6/schemas/{schema_id}"),
    "delete_schema": ("DELETE", "/v6/schemas/{schema_id}"),
}
WIRE_NAMES = {"user_prompt": "userPrompt", "schema_id": "schemaId", "bypass_preview": "bypassPreview", "run_id": "runId", "sort_by": "sortBy", "job_id": "jobId"}
TEXT_ACKS = {"delete_workflow": "Workflow deleted", "pause_workflow": "Workflow paused", "schedule_workflow": "Workflow scheduled"}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class KadoaNode(WorkflowNode):
    integration_type = "automation-kadoa"
    connection_evidence = ConnectionEvidence(noun="workflows", operation="list_workflows")

    @classmethod
    def get_config_model(cls):
        return KadoaConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Kadoa API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for name in re.findall(r"\{(\w+)\}", path):
            path = path.replace("{" + name + "}", quote(values.pop(name), safe=""))
        payload = {WIRE_NAMES.get(k, k): v for k, v in values.items()}
        kwargs = {"params": payload} if method == "GET" else {"json": payload} if payload else {}
        try:
            async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"x-api-key": secret, "Accept": "application/json, text/plain"}, **kwargs)
        except httpx.HTTPError:
            return {"status": "error", "error": "Kadoa request did not complete; inspect the workflow before retrying a write.", "write_outcome": "unknown" if method != "GET" else None}
        if not 200 <= response.status_code < 300:
            message = response.text[:2000]
            return _redact({"status": "error", "http_status": response.status_code,
                "error": message or "Kadoa rejected the request", "write_outcome": "unknown" if method != "GET" and response.status_code >= 500 else None}, secret)
        try:
            if len(response.content) > 20_000_000:
                raise ValueError("Response exceeds the JSON page bound")
            if op.operation in TEXT_ACKS:
                if response.text.strip() != TEXT_ACKS[op.operation]:
                    raise ValueError("Unexpected acknowledgment")
                data = {"message": response.text.strip()}
            else:
                data = response.json()
                if not isinstance(data, dict) or data.get("error") or data.get("success") is False:
                    raise ValueError("Unexpected API response")
                if op.operation == "list_workflows" and not isinstance(data.get("workflows"), list):
                    raise ValueError("Missing workflow list")
                if op.operation in {"list_schemas", "get_schema", "create_schema", "update_schema", "delete_schema"} and data.get("error") is not False:
                    raise ValueError("Missing schema acknowledgment")
            output = {"status": "success", "operation": op.operation, "http_status": response.status_code, "data": data}
            if op.operation == "list_workflows":
                output["items"] = data["workflows"]
        except (ValueError, TypeError):
            return {"status": "error", "error": "Kadoa returned an unexpected response; inspect the workflow before retrying a write.", "http_status": response.status_code, "write_outcome": "unknown" if method != "GET" else None}
        output = _redact(output, secret)
        await self.emit(output)
        return output
