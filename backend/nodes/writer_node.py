"""Writer API v1 automation, pinned to the provider's gateway API 1.0 contract.

Each operation maps to one endpoint. Cursor pagination, job status, citations
and model usage stay in the provider's response so workflows can continue them.
Docs: https://dev.writer.com/api-reference/api-keys
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.writer.com"


class WriterAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Writer API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.writer.com",
            "x-credential-instructions": "In Writer Control Center, open Security & compliance → API Keys, generate a key, and paste it here. Enable Knowledge graphs and files for the connection check and graph/file operations, Models for generation, and the permissions your applications need. NoClick checks the key by listing your Knowledge Graphs. Use a new API key: legacy keys stop working December 1, 2026."})
    credential_type: Literal["writer_api_key"] = Field("writer_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=8192, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


ResourceID = Annotated[str, Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")]


class _Page(_Input):
    limit: int = Field(50, ge=1, le=100, description="One page only. Continue using the returned first_id/last_id and has_more.")
    order: Literal["asc", "desc"] = "desc"
    before: ResourceID | None = None
    after: ResourceID | None = None

    @model_validator(mode="after")
    def one_cursor(self):
        if self.before and self.after:
            raise ValueError("Choose either before or after")
        return self


class _GraphID(_Input):
    graph_id: UUID = Field(..., description="Knowledge Graph UUID from Writer.")


class _FileID(_Input):
    file_id: ResourceID = Field(..., description="Writer file ID; upload files in Writer before referencing them.")


class _ApplicationID(_Input):
    application_id: ResourceID = Field(..., description="No-code application ID from Writer AI Studio.")


class _JobID(_Input):
    job_id: UUID


class WriterMessage(_Input):
    role: Literal["system", "user", "assistant"]
    content: str


class WriterApplicationInput(_Input):
    id: str = Field(..., min_length=1, description="Input field name defined by the selected application.")
    value: list[str] = Field(..., description="Values for the field; file inputs take existing Writer file IDs.")


class _Generation(_Input):
    model: str = Field("palmyra-x5", description="Writer or configured external model ID.")
    max_tokens: int | None = Field(None, ge=1)
    temperature: float | None = None
    top_p: float | None = None


class WriterChatConfig(_Generation):
    """POST /v1/chat."""
    operation: Literal["chat"] = Field("chat", json_schema_extra={"ui:hidden": True, "x-display-name": "Chat"})
    messages: list[WriterMessage] = Field(..., min_length=1)


class WriterGenerateTextConfig(_Generation):
    """POST /v1/completions."""
    operation: Literal["generate_text"] = Field("generate_text", json_schema_extra={"ui:hidden": True, "x-display-name": "Generate Text"})
    prompt: str = Field(..., min_length=1, json_schema_extra={"ui:widget": "textarea"})


class WriterListModelsConfig(_Input):
    """GET /v1/models."""
    operation: Literal["list_models"] = Field("list_models", json_schema_extra={"ui:hidden": True, "x-display-name": "List Models"})


class WriterListGraphsConfig(_Page):
    """GET /v1/graphs."""
    operation: Literal["list_graphs"] = Field("list_graphs", json_schema_extra={"ui:hidden": True, "x-display-name": "List Graphs"})
    before: UUID | None = None
    after: UUID | None = None
    team_ids: list[int] | None = Field(None, description="Repeat team filters; omitted returns org-wide graphs only.")


class WriterCreateGraphConfig(_Input):
    """POST /v1/graphs."""
    operation: Literal["create_graph"] = Field("create_graph", json_schema_extra={"ui:hidden": True, "x-display-name": "Create Graph"})
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=255)
    team_ids: list[int] | None = None


class WriterGetGraphConfig(_GraphID):
    """GET /v1/graphs/{graph_id}."""
    operation: Literal["get_graph"] = Field("get_graph", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Graph"})


class WriterUpdateGraphConfig(_GraphID):
    """PUT /v1/graphs/{graph_id}."""
    operation: Literal["update_graph"] = Field("update_graph", json_schema_extra={"ui:hidden": True, "x-display-name": "Update Graph"})
    name: str | None = Field(None, max_length=255)
    description: str | None = Field(None, max_length=255)
    team_ids: list[int] | None = Field(None, description="Replaces team assignment; [] makes the graph org-wide. Omit to retain it.")

    @model_validator(mode="after")
    def changed(self):
        if self.name is None and self.description is None and self.team_ids is None:
            raise ValueError("Provide a graph field to update")
        return self


class WriterDeleteGraphConfig(_GraphID):
    """DELETE /v1/graphs/{graph_id}."""
    operation: Literal["delete_graph"] = Field("delete_graph", json_schema_extra={"ui:hidden": True, "x-display-name": "Delete Graph"})


class WriterAskGraphConfig(_Input):
    """POST /v1/graphs/question."""
    operation: Literal["ask_graph"] = Field("ask_graph", json_schema_extra={"ui:hidden": True, "x-display-name": "Ask Graph"})
    graph_ids: list[UUID] = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    subqueries: bool = False


class WriterAddFileToGraphConfig(_GraphID, _FileID):
    """POST /v1/graphs/{graph_id}/file."""
    operation: Literal["add_file_to_graph"] = Field("add_file_to_graph", json_schema_extra={"ui:hidden": True, "x-display-name": "Add File To Graph"})


class WriterRemoveFileFromGraphConfig(_GraphID, _FileID):
    """DELETE /v1/graphs/{graph_id}/file/{file_id}."""
    operation: Literal["remove_file_from_graph"] = Field("remove_file_from_graph", json_schema_extra={"ui:hidden": True, "x-display-name": "Remove File From Graph"})


class WriterListFilesConfig(_Page):
    """GET /v1/files."""
    operation: Literal["list_files"] = Field("list_files", json_schema_extra={"ui:hidden": True, "x-display-name": "List Files"})
    graph_id: UUID | None = None
    status: Literal["in_progress", "completed", "failed"] | None = None
    file_types: str | None = Field(None, description="Comma-separated extensions, for example pdf,jpg,docx.")


class WriterGetFileConfig(_FileID):
    """GET /v1/files/{file_id}."""
    operation: Literal["get_file"] = Field("get_file", json_schema_extra={"ui:hidden": True, "x-display-name": "Get File"})


class WriterDeleteFileConfig(_FileID):
    """DELETE /v1/files/{file_id}."""
    operation: Literal["delete_file"] = Field("delete_file", json_schema_extra={"ui:hidden": True, "x-display-name": "Delete File"})


class WriterRetryFilesConfig(_Input):
    """POST /v1/files/retry."""
    operation: Literal["retry_files"] = Field("retry_files", json_schema_extra={"ui:hidden": True, "x-display-name": "Retry Files"})
    file_ids: list[UUID] = Field(..., min_length=1)


class WriterListApplicationsConfig(_Page):
    """GET /v1/applications."""
    operation: Literal["list_applications"] = Field("list_applications", json_schema_extra={"ui:hidden": True, "x-display-name": "List Applications"})
    before: UUID | None = None
    after: UUID | None = None
    type: Literal["generation"] = Field("generation", description="Application type supported by this API.")


class WriterGetApplicationConfig(_ApplicationID):
    """GET /v1/applications/{application_id}."""
    operation: Literal["get_application"] = Field("get_application", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Application"})


class WriterGenerateApplicationConfig(_ApplicationID):
    """POST /v1/applications/{application_id}."""
    operation: Literal["generate_application"] = Field("generate_application", json_schema_extra={"ui:hidden": True, "x-display-name": "Generate Application"})
    application_id: UUID
    inputs: list[WriterApplicationInput]


class WriterListJobsConfig(_ApplicationID):
    """GET /v1/applications/{application_id}/jobs."""
    operation: Literal["list_jobs"] = Field("list_jobs", json_schema_extra={"ui:hidden": True, "x-display-name": "List Jobs"})
    status: Literal["in_progress", "failed", "completed"] | None = None
    offset: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=100)


class WriterCreateJobConfig(_ApplicationID):
    """POST /v1/applications/{application_id}/jobs."""
    operation: Literal["create_job"] = Field("create_job", json_schema_extra={"ui:hidden": True, "x-display-name": "Create Job"})
    inputs: list[WriterApplicationInput]


class WriterGetJobConfig(_JobID):
    """GET /v1/applications/jobs/{job_id}."""
    operation: Literal["get_job"] = Field("get_job", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Job"})


class WriterRetryJobConfig(_JobID):
    """POST /v1/applications/jobs/{job_id}/retry."""
    operation: Literal["retry_job"] = Field("retry_job", json_schema_extra={"ui:hidden": True, "x-display-name": "Retry Job"})


class WriterListApplicationGraphsConfig(_ApplicationID):
    """GET /v1/applications/{application_id}/graphs."""
    operation: Literal["list_application_graphs"] = Field("list_application_graphs", json_schema_extra={"ui:hidden": True, "x-display-name": "List Application Graphs"})


class WriterAssociateApplicationGraphsConfig(_ApplicationID):
    """PUT /v1/applications/{application_id}/graphs."""
    operation: Literal["associate_application_graphs"] = Field("associate_application_graphs", json_schema_extra={"ui:hidden": True, "x-display-name": "Associate Application Graphs"})
    graph_ids: list[UUID] = Field(..., description="Replaces all associated graphs; [] clears them. Chat-capable applications only.")


class WriterParsePDFConfig(_FileID):
    """POST /v1/tools/pdf-parser/{file_id}."""
    operation: Literal["parse_pdf"] = Field("parse_pdf", json_schema_extra={"ui:hidden": True, "x-display-name": "Parse PDF"})
    format: Literal["text", "markdown"] = "markdown"


WriterConfig = Annotated[Union[
    WriterChatConfig,
    WriterGenerateTextConfig,
    WriterListModelsConfig,
    WriterListGraphsConfig,
    WriterCreateGraphConfig,
    WriterGetGraphConfig,
    WriterUpdateGraphConfig,
    WriterDeleteGraphConfig,
    WriterAskGraphConfig,
    WriterAddFileToGraphConfig,
    WriterRemoveFileFromGraphConfig,
    WriterListFilesConfig,
    WriterGetFileConfig,
    WriterDeleteFileConfig,
    WriterRetryFilesConfig,
    WriterListApplicationsConfig,
    WriterGetApplicationConfig,
    WriterGenerateApplicationConfig,
    WriterListJobsConfig,
    WriterCreateJobConfig,
    WriterGetJobConfig,
    WriterRetryJobConfig,
    WriterListApplicationGraphsConfig,
    WriterAssociateApplicationGraphsConfig,
    WriterParsePDFConfig
], Field(discriminator="operation")]


class WriterFullConfig(NodeConfig[WriterConfig, WriterAPIKeyCredential]):
    pass


ROUTES = {'chat': ('POST', '/v1/chat'),
 'generate_text': ('POST', '/v1/completions'),
 'list_models': ('GET', '/v1/models'),
 'list_graphs': ('GET', '/v1/graphs'),
 'create_graph': ('POST', '/v1/graphs'),
 'get_graph': ('GET', '/v1/graphs/{graph_id}'),
 'update_graph': ('PUT', '/v1/graphs/{graph_id}'),
 'delete_graph': ('DELETE', '/v1/graphs/{graph_id}'),
 'ask_graph': ('POST', '/v1/graphs/question'),
 'add_file_to_graph': ('POST', '/v1/graphs/{graph_id}/file'),
 'remove_file_from_graph': ('DELETE', '/v1/graphs/{graph_id}/file/{file_id}'),
 'list_files': ('GET', '/v1/files'),
 'get_file': ('GET', '/v1/files/{file_id}'),
 'delete_file': ('DELETE', '/v1/files/{file_id}'),
 'retry_files': ('POST', '/v1/files/retry'),
 'list_applications': ('GET', '/v1/applications'),
 'get_application': ('GET', '/v1/applications/{application_id}'),
 'generate_application': ('POST', '/v1/applications/{application_id}'),
 'list_jobs': ('GET', '/v1/applications/{application_id}/jobs'),
 'create_job': ('POST', '/v1/applications/{application_id}/jobs'),
 'get_job': ('GET', '/v1/applications/jobs/{job_id}'),
 'retry_job': ('POST', '/v1/applications/jobs/{job_id}/retry'),
 'list_application_graphs': ('GET', '/v1/applications/{application_id}/graphs'),
 'associate_application_graphs': ('PUT', '/v1/applications/{application_id}/graphs'),
 'parse_pdf': ('POST', '/v1/tools/pdf-parser/{file_id}')}

QUERY_FIELDS = {'list_graphs': ('limit', 'order', 'before', 'after', 'team_ids'),
 'list_files': ('limit', 'order', 'before', 'after', 'graph_id', 'status', 'file_types'),
 'list_applications': ('limit', 'order', 'before', 'after', 'type'),
 'list_jobs': ('status', 'offset', 'limit')}


class WriterNode(WorkflowNode):
    integration_type = "automation-writer"
    connection_evidence = ConnectionEvidence(noun="Knowledge Graphs", operation="list_graphs")

    @classmethod
    def get_config_model(cls):
        return WriterFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Writer API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        fields = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for key in re.findall(r"\{(\w+)\}", path):
            path = path.replace("{" + key + "}", quote(str(fields.pop(key)), safe=""))
        params = {key: fields.pop(key) for key in QUERY_FIELDS.get(config.operation, ()) if key in fields}
        if config.operation in {"chat", "generate_text", "ask_graph", "generate_application"}:
            fields["stream"] = False
        async with guarded_async_client(timeout=120, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Bearer " + self.config.credentials.api_key, "Accept": "application/json"},
                params=params, **({"json": fields} if fields and method in {"POST", "PUT"} else {}))
        if not 200 <= response.status_code < 300:
            message = response.text[:2000].replace(self.config.credentials.api_key, "[redacted]")
            raise ValueError(f"Writer HTTP {response.status_code}: {message}")
        if response.status_code == 204:
            return {"http_status": 204}
        if len(response.content) > 20_000_000:
            raise ValueError("Writer response exceeds 20 MB")
        data = response.json()
        job_result = (config.operation == "get_job" and isinstance(data, dict)
            and isinstance(data.get("id"), str) and data.get("status") in {"in_progress", "failed", "completed"}
            and isinstance(data.get("application_id"), str) and isinstance(data.get("created_at"), str))
        if not isinstance(data, dict) or ("error" in data and not job_result):
            raise ValueError("Writer returned an unexpected response or error envelope")
        if config.operation == "list_graphs" and not isinstance(data.get("data"), list):
            raise ValueError("Writer graph listing is missing its rows")
        # Keep job failure metadata separate from the workflow error envelope.
        return {"job": data} if config.operation == "get_job" else data
