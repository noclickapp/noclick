"""PromptLayer prompt releases, request feedback, tables and evaluations.

Each operation makes one request against the published REST contract. Responses
retain the provider's pagination and asynchronous job identifiers for later reads.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.promptlayer.com"


class PromptLayerAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="PromptLayer API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.promptlayer.com/reference/introduction",
            "x-credential-instructions": "Create an API key in PromptLayer Settings, then paste it here. NoClick checks the key by reading AI workflows in its workspace. Use a key with permissions for the operations you need.",
        },
    )
    credential_type: Literal["promptlayer_api_key"] = Field("promptlayer_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API key as text")
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page to read. This operation returns one page; use provider pagination for the next page.")
    per_page: int = Field(10, ge=1, le=100)


class _Version(_Input):
    version: int | None = Field(None, ge=1, description="Specific prompt version; mutually exclusive with label.")
    label: str | None = Field(None, min_length=1, description="Release label; mutually exclusive with version.")

    @model_validator(mode="after")
    def version_or_label(self):
        if self.version is not None and self.label is not None:
            raise ValueError("Choose either a version or a release label")
        return self


class _Prompt(_Version):
    identifier: str = Field(..., min_length=1, max_length=512, description="Prompt name or ID.")

    @field_validator("identifier")
    @classmethod
    def identifier_segment(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use a prompt name or ID without control characters")
        return value


class PromptLayerListWorkflowsConfig(_Page):
    """List workspace AI workflows and retain provider pagination."""
    operation: Literal["list_workflows"] = Field("list_workflows", json_schema_extra={"ui:hidden": True})
    sort_by: Literal["created_at", "updated_at", "name", "id"] | None = None
    sort_order: Literal["asc", "desc"] = "desc"


class PromptLayerGetPromptConfig(_Prompt):
    """Get raw chat or completion content and version metadata."""
    operation: Literal["get_prompt"] = Field("get_prompt", json_schema_extra={"ui:hidden": True})
    resolve_snippets: bool = True
    include_llm_kwargs: bool = False


class PromptLayerRenderPromptConfig(_Prompt):
    """Retrieve a template with input variables applied; does not run an LLM."""
    operation: Literal["render_prompt"] = Field("render_prompt", json_schema_extra={"ui:hidden": True})
    input_variables: dict[str, str] | None = None
    metadata_filters: dict[str, str] | None = None
    provider: Literal["openai", "anthropic"] | None = None
    model: str | None = None
    model_parameter_overrides: dict[str, Any] | None = None


class PromptLayerPublishPromptConfig(_Input):
    """Publish a new prompt or version, optionally moving release labels to it."""
    operation: Literal["publish_prompt"] = Field("publish_prompt", json_schema_extra={"ui:hidden": True})
    prompt_name: str = Field(..., min_length=1, max_length=512)
    prompt_template: dict[str, Any] = Field(..., description="PromptLayer template object: type chat with messages, or type completion with content. Use PromptLayer content blocks from the publish API docs.")
    tags: list[str] | None = None
    folder_id: int | None = Field(None, ge=1)
    commit_message: str | None = Field(None, max_length=72)
    metadata: dict[str, Any] | None = None
    release_labels: list[str] | None = None

    @field_validator("prompt_template")
    @classmethod
    def template(cls, value):
        kind = value.get("type")
        content = value.get("messages" if kind == "chat" else "content")
        if kind not in {"chat", "completion"} or not isinstance(content, list):
            raise ValueError("Supply a PromptLayer chat/messages or completion/content template")
        return value


class PromptLayerPatchPromptConfig(_Prompt):
    """Create a version from a base version or label, replacing selected fields."""
    operation: Literal["patch_prompt"] = Field("patch_prompt", json_schema_extra={"ui:hidden": True})
    messages: list[dict[str, Any]] | dict[str, Any] | None = Field(None, description="Array replaces all chat messages; object patches string message indices.")
    content: list[dict[str, Any]] | dict[str, Any] | None = Field(None, description="Completion content replacement or index patch.")
    model_parameters: dict[str, Any] | None = None
    commit_message: str | None = None
    release_labels: list[str] | None = None

    @model_validator(mode="after")
    def changes(self):
        if not any(getattr(self, key) is not None for key in ("messages", "content", "model_parameters", "commit_message", "release_labels")):
            raise ValueError("Supply at least one prompt version change")
        return self


class PromptLayerListLabelsConfig(_Input):
    """List release labels for one prompt."""
    operation: Literal["list_labels"] = Field("list_labels", json_schema_extra={"ui:hidden": True})
    identifier: str = Field(..., min_length=1, max_length=512)
    _identifier = field_validator("identifier")(PromptLayerGetPromptConfig.identifier_segment.__func__)


class PromptLayerCreateLabelConfig(_Input):
    """Create a release label pointing to a prompt version."""
    operation: Literal["create_label"] = Field("create_label", json_schema_extra={"ui:hidden": True})
    prompt_id: int = Field(..., ge=1)
    prompt_version_number: int = Field(..., ge=1)
    name: str = Field(..., min_length=1)


class PromptLayerMoveLabelConfig(_Input):
    """Move an existing release label to a different version."""
    operation: Literal["move_label"] = Field("move_label", json_schema_extra={"ui:hidden": True})
    prompt_label_id: int = Field(..., ge=1)
    prompt_version_number: int = Field(..., ge=1)


class PromptLayerDeleteLabelConfig(_Input):
    """Delete a release label without deleting its prompt."""
    operation: Literal["delete_label"] = Field("delete_label", json_schema_extra={"ui:hidden": True})
    prompt_label_id: int = Field(..., ge=1)


class PromptLayerTrackMetadataConfig(_Input):
    """Associate custom metadata with a logged request."""
    operation: Literal["track_metadata"] = Field("track_metadata", json_schema_extra={"ui:hidden": True})
    request_id: int = Field(..., ge=1)
    metadata: dict[str, Any]


class PromptLayerTrackScoreConfig(_Input):
    """Track a named or default score from 0 to 100."""
    operation: Literal["track_score"] = Field("track_score", json_schema_extra={"ui:hidden": True})
    request_id: int = Field(..., ge=1)
    score: int = Field(..., ge=0, le=100)
    name: str | None = None


class PromptLayerTrackPromptConfig(_Version):
    """Associate a request with a prompt and its input variables."""
    operation: Literal["track_prompt"] = Field("track_prompt", json_schema_extra={"ui:hidden": True})
    request_id: int = Field(..., ge=1)
    prompt_name: str = Field(..., min_length=1)
    prompt_input_variables: dict[str, Any] | None = None


class PromptLayerGetRequestConfig(_Input):
    """Read a logged request's prompt, usage, timing and cost."""
    operation: Literal["get_request"] = Field("get_request", json_schema_extra={"ui:hidden": True})
    request_id: int = Field(..., ge=1)


class PromptLayerGetTraceConfig(_Input):
    """Read the spans belonging to a trace."""
    operation: Literal["get_trace"] = Field("get_trace", json_schema_extra={"ui:hidden": True})
    trace_id: str = Field(..., min_length=1, max_length=512)
    _identifier = field_validator("trace_id")(PromptLayerGetPromptConfig.identifier_segment.__func__)


class _Table(_Input):
    table_id: UUID = Field(..., description="Table UUID from PromptLayer.")


class _Sheet(_Table):
    sheet_id: UUID = Field(..., description="Sheet UUID within the table.")


class _Cursor(_Input):
    cursor: str | None = Field(None, description="Opaque next_cursor from the previous page with the same filters.")
    limit: int = Field(20, ge=1, le=100)
    order: Literal["asc", "desc"] = "asc"


class PromptLayerListTablesConfig(_Cursor):
    """List tables in the key's workspace, retaining the next cursor."""
    operation: Literal["list_tables"] = Field("list_tables", json_schema_extra={"ui:hidden": True})
    name: str | None = None
    folder_id: int | None = Field(None, ge=1)
    prompt_id: int | None = Field(None, ge=1)


class PromptLayerCreateTableConfig(_Input):
    """Create a table, optionally including a default sheet and text column."""
    operation: Literal["create_table"] = Field("create_table", json_schema_extra={"ui:hidden": True})
    title: str | None = None
    folder_id: int | None = Field(None, ge=1)
    create_default_sheet: bool = True


class PromptLayerGetTableConfig(_Table):
    """Read a table and its sheet metadata."""
    operation: Literal["get_table"] = Field("get_table", json_schema_extra={"ui:hidden": True})


class PromptLayerListSheetsConfig(_Table, _Cursor):
    """List sheets belonging to one table."""
    operation: Literal["list_sheets"] = Field("list_sheets", json_schema_extra={"ui:hidden": True})


class PromptLayerCreateSheetConfig(_Table):
    """Create a blank sheet with the provider's default text column scaffold."""
    operation: Literal["create_sheet"] = Field("create_sheet", json_schema_extra={"ui:hidden": True})
    title: str | None = None
    index: int | None = Field(None, ge=0)


class PromptLayerGetSheetConfig(_Sheet):
    """Read sheet details and version count."""
    operation: Literal["get_sheet"] = Field("get_sheet", json_schema_extra={"ui:hidden": True})


class PromptLayerListRowsConfig(_Sheet, _Cursor):
    """Read one page of rows with optional column and execution metadata."""
    operation: Literal["list_rows"] = Field("list_rows", json_schema_extra={"ui:hidden": True})
    include_columns: bool | None = None
    include_row_count: bool = True
    include_system_columns: bool = False
    include_execution_metadata_aggregates: bool = False


class PromptLayerAddRowsConfig(_Sheet):
    """Append rows; computed cells remain stale until explicitly recalculated."""
    operation: Literal["add_rows"] = Field("add_rows", json_schema_extra={"ui:hidden": True})
    count: int = Field(1, ge=1, le=100)
    values: list[dict[str, Any]] | None = Field(None, max_length=100, description="One map of text-column UUID to value per appended row.")

    @model_validator(mode="after")
    def row_count(self):
        if self.values is not None and len(self.values) != self.count:
            raise ValueError("Provide exactly count value maps, or omit values")
        if self.values is not None:
            for row in self.values:
                for key in row:
                    UUID(key)
        return self


class PromptLayerRecalculateSheetConfig(_Sheet):
    """Queue recalculation; preserve any confirmation request instead of approving it automatically."""
    operation: Literal["recalculate_sheet"] = Field("recalculate_sheet", json_schema_extra={"ui:hidden": True})
    column_ids: list[UUID] | None = None
    row_ids: list[Annotated[int, Field(ge=0)]] | None = None
    statuses: list[Literal["STALE", "QUEUED", "DISPATCHED", "RUNNING", "COMPLETED", "FAILED"]] | None = Field(None, description="Omit for stale cells, or pass an empty list for all statuses. Recalculation can consume provider credits.")
    confirmation_token: str | None = Field(None, description="Token explicitly returned by a prior confirmation response for this request.")


class PromptLayerGetSheetOperationConfig(_Sheet):
    """Poll a queued sheet recalculation without starting another run."""
    operation: Literal["get_sheet_operation"] = Field("get_sheet_operation", json_schema_extra={"ui:hidden": True})
    operation_id: str = Field(..., min_length=1, max_length=512)
    _identifier = field_validator("operation_id")(PromptLayerGetPromptConfig.identifier_segment.__func__)


class PromptLayerGetSheetScoreConfig(_Sheet):
    """Read aggregate and per-column scores and calculation status."""
    operation: Literal["get_sheet_score"] = Field("get_sheet_score", json_schema_extra={"ui:hidden": True})


PromptLayerConfig = Annotated[Union[
    PromptLayerListWorkflowsConfig, PromptLayerGetPromptConfig, PromptLayerRenderPromptConfig,
    PromptLayerPublishPromptConfig, PromptLayerPatchPromptConfig, PromptLayerListLabelsConfig,
    PromptLayerCreateLabelConfig, PromptLayerMoveLabelConfig, PromptLayerDeleteLabelConfig,
    PromptLayerTrackMetadataConfig, PromptLayerTrackScoreConfig, PromptLayerTrackPromptConfig,
    PromptLayerGetRequestConfig, PromptLayerGetTraceConfig, PromptLayerListTablesConfig,
    PromptLayerCreateTableConfig, PromptLayerGetTableConfig, PromptLayerListSheetsConfig,
    PromptLayerCreateSheetConfig, PromptLayerGetSheetConfig, PromptLayerListRowsConfig,
    PromptLayerAddRowsConfig, PromptLayerRecalculateSheetConfig, PromptLayerGetSheetOperationConfig,
    PromptLayerGetSheetScoreConfig,
], Field(discriminator="operation")]


class PromptLayerFullConfig(NodeConfig[PromptLayerConfig, PromptLayerAPIKeyCredential]):
    pass


# operation -> HTTP method, contract route, path fields, query fields, success statuses
ROUTES = {
    "list_workflows": ("GET", "/workflows", (), ("page", "per_page", "sort_by", "sort_order"), (200,)),
    "get_prompt": ("GET", "/prompt-templates/{identifier}", ("identifier",), ("version", "label", "resolve_snippets", "include_llm_kwargs"), (200,)),
    "render_prompt": ("POST", "/prompt-templates/{identifier}", ("identifier",), (), (200,)),
    "publish_prompt": ("POST", "/rest/prompt-templates", (), (), (200,)),
    "patch_prompt": ("PATCH", "/rest/prompt-templates/{identifier}", ("identifier",), (), (201,)),
    "list_labels": ("GET", "/prompt-templates/{identifier}/labels", ("identifier",), (), (200,)),
    "create_label": ("POST", "/prompts/{prompt_id}/label", ("prompt_id",), (), (200,)),
    "move_label": ("PATCH", "/prompt-labels/{prompt_label_id}", ("prompt_label_id",), (), (200,)),
    "delete_label": ("DELETE", "/prompt-labels/{prompt_label_id}", ("prompt_label_id",), (), (204,)),
    "track_metadata": ("POST", "/rest/track-metadata", (), (), (200,)),
    "track_score": ("POST", "/rest/track-score", (), (), (200,)),
    "track_prompt": ("POST", "/rest/track-prompt", (), (), (200,)),
    "get_request": ("GET", "/api/public/v2/requests/{request_id}", ("request_id",), (), (200,)),
    "get_trace": ("GET", "/api/public/v2/traces/{trace_id}", ("trace_id",), (), (200,)),
    "list_tables": ("GET", "/api/public/v2/tables", (), ("cursor", "limit", "order", "name", "folder_id", "prompt_id"), (200,)),
    "create_table": ("POST", "/api/public/v2/tables", (), (), (201,)),
    "get_table": ("GET", "/api/public/v2/tables/{table_id}", ("table_id",), (), (200,)),
    "list_sheets": ("GET", "/api/public/v2/tables/{table_id}/sheets", ("table_id",), ("cursor", "limit", "order"), (200,)),
    "create_sheet": ("POST", "/api/public/v2/tables/{table_id}/sheets", ("table_id",), (), (201,)),
    "get_sheet": ("GET", "/api/public/v2/tables/{table_id}/sheets/{sheet_id}", ("table_id", "sheet_id"), (), (200,)),
    "list_rows": ("GET", "/api/public/v2/tables/{table_id}/sheets/{sheet_id}/rows", ("table_id", "sheet_id"), ("cursor", "limit", "order", "include_columns", "include_row_count", "include_system_columns", "include_execution_metadata_aggregates"), (200,)),
    "add_rows": ("POST", "/api/public/v2/tables/{table_id}/sheets/{sheet_id}/rows", ("table_id", "sheet_id"), (), (201,)),
    "recalculate_sheet": ("POST", "/api/public/v2/tables/{table_id}/sheets/{sheet_id}/operations", ("table_id", "sheet_id"), (), (200, 202)),
    "get_sheet_operation": ("GET", "/api/public/v2/tables/{table_id}/sheets/{sheet_id}/operations/{operation_id}", ("table_id", "sheet_id", "operation_id"), (), (200,)),
    "get_sheet_score": ("GET", "/api/public/v2/tables/{table_id}/sheets/{sheet_id}/score", ("table_id", "sheet_id"), (), (200,)),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    return value


class PromptLayerNode(WorkflowNode):
    integration_type = "automation-promptlayer"
    connection_evidence = ConnectionEvidence(noun="PromptLayer workspace workflows", operation="list_workflows", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return PromptLayerFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a PromptLayer API key")
        method, route, path_fields, query_fields, expected = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for key in path_fields:
            route = route.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        params = {key: values.pop(key) for key in query_fields if key in values}
        if config.operation == "publish_prompt":
            values = {
                "prompt_template": {key: values[key] for key in ("prompt_name", "tags", "folder_id") if key in values},
                "prompt_version": {key: values[key] for key in ("prompt_template", "commit_message", "metadata") if key in values},
                **({"release_labels": values["release_labels"]} if "release_labels" in values else {}),
            }
        if config.operation == "recalculate_sheet":
            values["operation"] = "recalculate"
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(
                    method, BASE_URL + route,
                    headers={"X-API-KEY": credential.api_key, "Accept": "application/json"},
                    params=params, **({"json": values} if method in {"POST", "PATCH"} else {}),
                )
        except httpx.HTTPError:
            raise ValueError("PromptLayer request did not complete. Inspect the provider before retrying a write.") from None
        if response.status_code not in expected:
            detail = response.text.replace(credential.api_key, "[redacted]")[:2000]
            raise ValueError(f"PromptLayer HTTP {response.status_code}: {detail}")
        if response.status_code == 204:
            return {"data": None, "http_status": 204}
        try:
            result = response.json()
        except ValueError:
            raise ValueError("PromptLayer returned an invalid JSON response") from None
        if not isinstance(result, dict):
            raise ValueError("PromptLayer returned an unexpected response shape")
        confirmation = config.operation == "recalculate_sheet" and result.get("requires_confirmation") is True
        if (result.get("success") is False and not confirmation) or result.get("error") or result.get("errors"):
            raise ValueError("PromptLayer: " + str(_redact(result, credential.api_key))[:2000])
        if config.operation == "list_workflows":
            if not isinstance(result.get("items"), list) or any(not isinstance(row, dict) for row in result["items"]):
                raise ValueError("PromptLayer returned an invalid workflow list")
        return {"data": _redact(result, credential.api_key), "http_status": response.status_code}
