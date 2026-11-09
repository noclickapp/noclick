"""AI21 Studio file library, Jamba chat and Maestro runs.

Contract: https://api.ai21.com/openapi.json (1.0.0).
Authentication: https://docs.ai21.com/reference/authentication.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, Json, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE = "https://api.ai21.com/studio/v1"
JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class StudioByAI21LabsAPIKey(BaseModel):
    model_config = ConfigDict(title="Studio By AI21 Labs API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.ai21.com/docs/create-api-key",
            "x-credential-instructions": "In AI21 Studio, open Settings → API Keys, create a workspace key and paste it here. NoClick reads your workspace file library to check the connection.",
        })
    credential_type: Literal["studio_by_ai21_labs_api_key"] = Field("studio_by_ai21_labs_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class ListFiles(_Input):
    """List one page of workspace files, optionally filtered by metadata."""
    operation: Literal["list_files"] = "list_files"
    name: str | None = Field(None, description="Exact uploaded filename.")
    path: str | None = Field(None, description="Library path prefix.")
    status: Literal["DB_RECORD_CREATED", "UPLOADED", "UPLOAD_FAILED", "PROCESSED", "PROCESSING_FAILED"] | None = None
    label: Json[list[str]] | None = Field(None, description="JSON array of case-sensitive labels.", json_schema_extra=JSON_EDITOR)
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0, description="Use next_offset from the preceding full page.")


class _File(_Input):
    file_id: UUID = Field(..., description="File UUID returned by upload or list files.")


class GetFile(_File):
    """Read metadata for one library file."""
    operation: Literal["get_file"] = "get_file"


class UpdateFile(_File):
    """Replace file labels or the public URL metadata."""
    operation: Literal["update_file"] = "update_file"
    labels: Json[list[str]] | None = Field(None, description="JSON array replacing all labels; [] clears them.", json_schema_extra=JSON_EDITOR)
    publicUrl: str | None = Field(None, title="Public URL", description="Metadata only; NoClick does not fetch this URL.")


class DeleteFile(_File):
    """Delete a file from the workspace library."""
    operation: Literal["delete_file"] = "delete_file"


class GetFileDownloadLink(_File):
    """Get a signed file download link without following it."""
    operation: Literal["get_file_download_link"] = "get_file_download_link"


class UploadFile(_Input):
    """Upload a UTF-8 text or HTML document with optional library metadata."""
    operation: Literal["upload_file"] = "upload_file"
    filename: str = Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.(txt|html)$", description="Unique filename ending in .txt or .html.")
    file_content: str = Field(..., min_length=1, max_length=5_000_000, description="UTF-8 document text (maximum 5 MB).", json_schema_extra={"ui:widget": "code_editor", "contentMediaType": "text/plain"})
    path: str | None = None
    labels: Json[list[str]] | None = Field(None, json_schema_extra=JSON_EDITOR)
    publicUrl: str | None = Field(None, title="Public URL", description="Source URL metadata only.")

    @field_validator("filename")
    @classmethod
    def file_name(cls, value):
        if any(c in value for c in ('/', '\\', '\r', '\n', '\x00', '"')) or not value.lower().endswith((".txt", ".html")):
            raise ValueError("Use a plain .txt or .html filename")
        return value

    @field_validator("file_content")
    @classmethod
    def file_size(cls, value):
        if len(value.encode("utf-8")) > 5_000_000:
            raise ValueError("File exceeds 5 MB")
        return value


class GetBatchStatus(_Input):
    """Read document ingestion counts for a library batch."""
    operation: Literal["get_batch_status"] = "get_batch_status"
    batch_id: UUID


class ChatMessage(_Input):
    role: Literal["system", "user", "assistant"]
    content: str


class CreateChatCompletion(_Input):
    """Generate a non-streaming Jamba chat response."""
    operation: Literal["create_chat_completion"] = "create_chat_completion"
    model: Literal["jamba-mini", "jamba-large", "jamba-large-1.7", "jamba-large-1.7-2025-07", "jamba-mini-2", "jamba-mini-2-2026-01"] = "jamba-large"
    messages: Json[Annotated[list[ChatMessage], Field(min_length=1)]] = Field(..., description='JSON message array, e.g. [{"role":"user","content":"Hello"}].', json_schema_extra=JSON_EDITOR)
    max_tokens: int = Field(1024, ge=1, le=4096)
    temperature: float | None = Field(None, ge=0, le=2)
    top_p: float | None = Field(None, gt=0, le=1)
    n: int = Field(1, ge=1, le=16)
    stop: Json[list[str]] | None = Field(None, json_schema_extra=JSON_EDITOR)

    @model_validator(mode="after")
    def distinct(self):
        if self.n > 1 and self.temperature == 0:
            raise ValueError("Multiple responses require nonzero temperature")
        return self


class Requirement(_Input):
    name: str
    description: str
    is_mandatory: bool = False


class CreateMaestroRun(_Input):
    """Start one Maestro run; use Get Maestro Run to retrieve its later status."""
    operation: Literal["create_maestro_run"] = "create_maestro_run"
    input: str = Field(..., min_length=1, description="Instruction for Maestro.")
    system_prompt: str | None = Field(None, description="Overall role and response style.")
    requirements: Json[Annotated[list[Requirement], Field(max_length=10)]] | None = Field(None, json_schema_extra=JSON_EDITOR)
    models: Json[Annotated[list[str], Field(max_length=1)]] | None = Field(None, json_schema_extra=JSON_EDITOR)
    budget: Literal["low", "medium", "high"] = "low"
    include: Json[list[Literal["data_sources", "requirements_result"]]] | None = Field(None, json_schema_extra=JSON_EDITOR)
    output_type: Json[dict] | None = Field(None, description="JSON Schema for structured output.", json_schema_extra=JSON_EDITOR)


class GetMaestroRun(_Input):
    """Retrieve a Maestro run's status, result and requirement scores."""
    operation: Literal["get_maestro_run"] = "get_maestro_run"
    execution_id: str = Field(..., min_length=1, max_length=256)


StudioByAI21LabsConfig = Annotated[Union[ListFiles, GetFile, UpdateFile, DeleteFile, GetFileDownloadLink,
    UploadFile, GetBatchStatus, CreateChatCompletion, CreateMaestroRun, GetMaestroRun], Field(discriminator="operation")]


class StudioByAI21LabsFullConfig(NodeConfig[StudioByAI21LabsConfig, StudioByAI21LabsAPIKey]):
    pass


class StudioByAI21LabsNode(WorkflowNode):
    integration_type = "automation-studio-by-ai21-labs"
    connection_evidence = ConnectionEvidence(operation="list_files", noun="workspace files")

    @classmethod
    def get_config_model(cls):
        return StudioByAI21LabsFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Studio By AI21 Labs API key")
        config = self.config.config
        operation = config.operation
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        method, path, kwargs = "GET", "/library/files", {}
        if operation == "list_files":
            kwargs["params"] = values
        elif operation == "upload_file":
            filename, content = values.pop("filename"), values.pop("file_content")
            mime = "text/html" if filename.lower().endswith(".html") else "text/plain"
            kwargs["data"] = values
            kwargs["files"] = {"file": (filename, content.encode("utf-8"), mime)}
            method = "POST"
        elif isinstance(config, _File):
            path += "/" + str(values.pop("file_id"))
            if operation == "update_file":
                method, kwargs = "PUT", {"json": values}
            elif operation == "delete_file":
                method = "DELETE"
            elif operation == "get_file_download_link":
                path += "/download"
        elif operation == "get_batch_status":
            path = "/library/batches/" + str(config.batch_id) + "/status"
        elif operation == "create_chat_completion":
            method, path, kwargs = "POST", "/chat/completions", {"json": {**values, "stream": False}}
        elif operation == "create_maestro_run":
            method, path, kwargs = "POST", "/maestro/runs", {"json": {**values, "stream": False}}
        elif operation == "get_maestro_run":
            path = "/maestro/runs/" + quote(config.execution_id, safe="")
        else:
            raise ValueError("Unsupported AI21 operation")
        async with httpx.AsyncClient(timeout=120, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Bearer " + self.config.credentials.api_key, "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            message = response.text[:2000].replace(self.config.credentials.api_key, "[redacted]")
            raise ValueError(f"AI21 HTTP {response.status_code}: {message}")
        if not response.content:
            if operation not in {"update_file", "delete_file"}:
                raise ValueError("AI21 returned an empty response")
            data = None
        else:
            data = response.json()
        if isinstance(data, dict) and ("detail" in data or (data.get("error") and operation not in {"create_maestro_run", "get_maestro_run"})):
            raise ValueError("AI21 returned an error: " + str(data).replace(self.config.credentials.api_key, "[redacted]")[:2000])
        result = {"status": "success", "data": data}
        if operation == "list_files":
            if not isinstance(data, list):
                raise ValueError("AI21 file list must be an array")
            result["next_offset"] = config.offset + len(data) if len(data) == config.limit else None
        return result
