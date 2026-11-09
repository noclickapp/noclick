"""Cradl AI document automation against the published v1 REST contract.

Each operation performs one API request. Access tokens are supplied by the
person connecting; this node does not store OAuth application secrets.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.cradl_ai import CRADL_AI_SCOPES

BASE_URL = "https://api.cradl.ai/v1"
DOCS_URL = "https://docs.cradl.ai/api-reference/introduction"
HEX_ID = r"[a-f0-9]{32}"
AgentId = Annotated[str, Field(pattern=r"^cradl:agent:" + HEX_ID + r"$")]
RunId = Annotated[str, Field(pattern=r"^cradl:run:" + HEX_ID + r"$")]
DocumentId = Annotated[str, Field(pattern=r"^(cradl|las):document:" + HEX_ID + r"$")]
ModelId = Annotated[str, Field(pattern=r"^((cradl|las):organization:[a-z0-9_-]+/)?(cradl|las):model:[a-z0-9_-]+$")]
PredictionId = Annotated[str, Field(pattern=r"^(cradl|las):prediction:" + HEX_ID + r"$")]
ValidationId = Annotated[str, Field(pattern=r"^cradl:validation:" + HEX_ID + r"$")]
TaskId = Annotated[str, Field(pattern=r"^cradl:task:" + HEX_ID + r"$")]
AgentRunId = Annotated[str, Field(pattern=r"^((cradl|las):organization:[a-z0-9_-]+/)?cradl:agent:[a-z0-9_-]+/cradl:run:[a-z0-9_-]+$")]
DatasetId = Annotated[str, Field(pattern=r"^(cradl|las):dataset:" + HEX_ID + r"$")]
Text = Annotated[str, Field(max_length=4096)]
ContentType = Literal["application/pdf", "image/jpeg", "image/png", "image/tiff", "image/webp", "message/rfc822"]
TaskStatus = Literal["ready", "in-progress", "succeeded", "failed", "cancelled"]
RunStatus = Literal["archived", "exported", "pending-export", "pending-predictions", "ready-for-review", "review-completed", "succeeded-predictions", "error", "running", "completed", "review-in-progress"]


class CradlAIAccessTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Cradl AI Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": DOCS_URL,
            "x-credential-instructions": "Paste a Cradl AI bearer access token obtained using your application's client credentials, as described in the API introduction. Give the application read access to agents for the connection check, plus the read/write scopes needed by your operations. Tokens expire: replace this token when it expires. NoClick does not refresh it or ask for your application secret.",
        },
    )
    credential_type: Literal["cradl_ai_access_token"] = Field("cradl_ai_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=16384, title="Access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the access token without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    next_token: Optional[str] = Field(None, max_length=4096, description="Opaque nextToken from the previous response. Keep the same operation and filters.")
    max_results: int = Field(20, ge=1, le=100, description="Maximum results in this page; this operation returns one page.")


class ListAgents(_Page):
    """List the connected account's agents."""
    operation: Literal["list_agents"] = "list_agents"


class GetAgent(_Input):
    """Read an agent and its resource IDs."""
    operation: Literal["get_agent"] = "get_agent"
    agent_id: AgentId


class ListAgentRuns(_Page):
    """List one page of runs for an agent."""
    operation: Literal["list_agent_runs"] = "list_agent_runs"
    agent_id: AgentId
    status: Optional[RunStatus] = None


class CreateAgentRun(_Input):
    """Start a run, optionally passing variables through to its output."""
    operation: Literal["create_agent_run"] = "create_agent_run"
    agent_id: AgentId
    variables: Optional[dict[str, Any]] = None


class GetAgentRun(_Input):
    """Read a run's status and output file references."""
    operation: Literal["get_agent_run"] = "get_agent_run"
    agent_id: AgentId
    run_id: RunId


class ArchiveAgentRun(GetAgentRun):
    """Archive a run using the documented status patch."""
    operation: Literal["archive_agent_run"] = "archive_agent_run"


class DeleteAgentRun(GetAgentRun):
    """Delete one explicitly selected agent run."""
    operation: Literal["delete_agent_run"] = "delete_agent_run"


class GetAgentStatistics(_Input):
    """Read an agent's processing statistics."""
    operation: Literal["get_agent_statistics"] = "get_agent_statistics"
    agent_id: AgentId


class ListDocuments(_Page):
    """List one page of documents, optionally within a dataset."""
    operation: Literal["list_documents"] = "list_documents"
    dataset_id: Optional[DatasetId] = None
    order: Optional[Literal["ascending", "descending"]] = None
    sort_by: Optional[Literal["createdTime"]] = None


class CreateDocument(_Input):
    """Create a document record with optional inline base64 file content.

    If content is omitted, upload separately to the returned fileUrl before
    expecting predictions. Creating the record alone does not upload a file.
    """
    operation: Literal["create_document"] = "create_document"
    name: Text
    description: Optional[Text] = None
    agent_run_id: Optional[AgentRunId] = None
    dataset_id: Optional[DatasetId] = None
    content_type: Optional[ContentType] = None
    content: Optional[str] = Field(None, min_length=1, max_length=6250000, description="Optional base64 document content, as accepted by POST /documents. Without it, this creates metadata only.")
    metadata: Optional[dict[str, Any]] = None
    retention_in_days: Optional[int] = Field(None, ge=1, le=1825)


class GetDocument(_Input):
    """Read a document's metadata and file references."""
    operation: Literal["get_document"] = "get_document"
    document_id: DocumentId


class UpdateDocument(_Input):
    """Patch only supplied document metadata fields."""
    operation: Literal["update_document"] = "update_document"
    document_id: DocumentId
    name: Optional[Text] = None
    description: Optional[Text] = None
    dataset_id: Optional[DatasetId] = None
    metadata: Optional[dict[str, Any]] = None
    retention_in_days: Optional[int] = Field(None, ge=1, le=1825)

    @model_validator(mode="after")
    def changes(self):
        if not any(getattr(self, n) is not None for n in ("name", "description", "dataset_id", "metadata", "retention_in_days")):
            raise ValueError("Supply at least one document field to update")
        return self


class DeleteDocument(GetDocument):
    """Delete one explicitly selected document."""
    operation: Literal["delete_document"] = "delete_document"


class ListPredictions(_Page):
    """List stored predictions, optionally filtered by model."""
    operation: Literal["list_predictions"] = "list_predictions"
    model_id: Optional[ModelId] = None
    order: Optional[Literal["ascending", "descending"]] = None
    sort_by: Optional[Literal["createdTime"]] = None


class CreatePrediction(_Input):
    """Extract structured data from an existing document using a model."""
    operation: Literal["create_prediction"] = "create_prediction"
    document_id: DocumentId
    model_id: ModelId
    agent_run_id: Optional[AgentRunId] = None
    name: Optional[Text] = None
    description: Optional[Text] = None
    metadata: Optional[dict[str, Any]] = None
    max_pages: Optional[int] = Field(None, ge=1, le=100)
    async_prediction: Optional[bool] = Field(None, description="Use asynchronous prediction; maps to the API's async field.")


class GetPrediction(_Input):
    """Read a stored prediction and its extracted values."""
    operation: Literal["get_prediction"] = "get_prediction"
    prediction_id: PredictionId


class ListModels(_Page):
    """List the account's extraction models."""
    operation: Literal["list_models"] = "list_models"


class GetModel(_Input):
    """Read an extraction model's configuration."""
    operation: Literal["get_model"] = "get_model"
    model_id: ModelId


class ListValidations(_Page):
    """List the account's human review configurations."""
    operation: Literal["list_validations"] = "list_validations"


class GetValidation(_Input):
    """Read a human review configuration."""
    operation: Literal["get_validation"] = "get_validation"
    validation_id: ValidationId


class ListValidationTasks(_Page):
    """List one page of review tasks within a validation."""
    operation: Literal["list_validation_tasks"] = "list_validation_tasks"
    validation_id: ValidationId
    status: Optional[TaskStatus] = None


class CreateValidationTask(_Input):
    """Create a review task; reuse an existing task when one already exists."""
    operation: Literal["create_validation_task"] = "create_validation_task"
    validation_id: ValidationId
    input: dict[str, Any] = Field(default_factory=dict, description="Review input; always sent, including an empty object.")
    agent_run_id: Optional[AgentRunId] = None
    name: Optional[Text] = None
    description: Optional[Text] = None
    metadata: Optional[dict[str, Any]] = None


class GetValidationTask(_Input):
    """Read a task and its current review state."""
    operation: Literal["get_validation_task"] = "get_validation_task"
    validation_id: ValidationId
    task_id: TaskId


class UpdateValidationTask(_Input):
    """Update review output or status, including completing or cancelling a task."""
    operation: Literal["update_validation_task"] = "update_validation_task"
    validation_id: ValidationId
    task_id: TaskId
    output: Optional[dict[str, Any]] = None
    status: Optional[TaskStatus] = None
    name: Optional[Text] = None
    description: Optional[Text] = None
    metadata: Optional[dict[str, Any]] = None

    @model_validator(mode="after")
    def changes(self):
        if not any(getattr(self, n) is not None for n in ("output", "status", "name", "description", "metadata")):
            raise ValueError("Supply at least one task field to update")
        return self


CradlAIConfig = Annotated[Union[
    ListAgents, GetAgent, ListAgentRuns, CreateAgentRun, GetAgentRun,
    ArchiveAgentRun, DeleteAgentRun, GetAgentStatistics,
    ListDocuments, CreateDocument, GetDocument, UpdateDocument, DeleteDocument,
    ListPredictions, CreatePrediction, GetPrediction, ListModels, GetModel,
    ListValidations, GetValidation, ListValidationTasks, CreateValidationTask,
    GetValidationTask, UpdateValidationTask,
], Field(discriminator="operation")]


class CradlAIFullConfig(NodeConfig[CradlAIConfig, CradlAIAccessTokenCredential]):
    pass


# Fixed routes keep every operation on exactly one published contract endpoint.
# The final tuple member is the list envelope, or None for a single resource.
ROUTES = {
    "list_agents": ("GET", "/agents", "agents"),
    "get_agent": ("GET", "/agents/{agent_id}", None),
    "list_agent_runs": ("GET", "/agents/{agent_id}/runs", "runs"),
    "create_agent_run": ("POST", "/agents/{agent_id}/runs", None),
    "get_agent_run": ("GET", "/agents/{agent_id}/runs/{run_id}", None),
    "archive_agent_run": ("PATCH", "/agents/{agent_id}/runs/{run_id}", None),
    "delete_agent_run": ("DELETE", "/agents/{agent_id}/runs/{run_id}", None),
    "get_agent_statistics": ("GET", "/agents/{agent_id}/statistics", None),
    "list_documents": ("GET", "/documents", "documents"),
    "create_document": ("POST", "/documents", None),
    "get_document": ("GET", "/documents/{document_id}", None),
    "update_document": ("PATCH", "/documents/{document_id}", None),
    "delete_document": ("DELETE", "/documents/{document_id}", None),
    "list_predictions": ("GET", "/predictions", "predictions"),
    "create_prediction": ("POST", "/predictions", None),
    "get_prediction": ("GET", "/predictions/{prediction_id}", None),
    "list_models": ("GET", "/models", "models"),
    "get_model": ("GET", "/models/{model_id}", None),
    "list_validations": ("GET", "/validations", "validations"),
    "get_validation": ("GET", "/validations/{validation_id}", None),
    "list_validation_tasks": ("GET", "/validations/{validation_id}/tasks", "tasks"),
    "create_validation_task": ("POST", "/validations/{validation_id}/tasks", None),
    "get_validation_task": ("GET", "/validations/{validation_id}/tasks/{task_id}", None),
    "update_validation_task": ("PATCH", "/validations/{validation_id}/tasks/{task_id}", None),
}
WIRE_NAMES = {
    "next_token": "nextToken", "max_results": "maxResults", "dataset_id": "datasetId",
    "sort_by": "sortBy", "model_id": "modelId", "document_id": "documentId",
    "agent_run_id": "agentRunId", "content_type": "contentType",
    "retention_in_days": "retentionInDays", "max_pages": "maxPages", "async_prediction": "async",
}


class CradlAINode(WorkflowNode):
    integration_type = "automation-cradl-ai"
    scope_registry = CRADL_AI_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_agents", noun="Cradl AI agents", label_keys=("name", "agentId"))

    @classmethod
    def get_config_model(cls):
        return CradlAIFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, CradlAIFullConfig) or self.config.credentials is None:
            raise ValueError("Connect a Cradl AI access token")
        config, credential = self.config.config, self.config.credentials
        method, template, envelope = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        values.pop("operation")
        for name in tuple(values):
            if "{" + name + "}" in template:
                template = template.replace("{" + name + "}", quote(values.pop(name), safe=""))
        payload = {WIRE_NAMES.get(k, k): v for k, v in values.items()}
        if config.operation == "archive_agent_run":
            payload = {"status": "archived"}
        headers = {"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"}
        kwargs = {"params": {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in payload.items()}} if method == "GET" else {}
        if method in {"POST", "PATCH"}:
            headers["Content-Type"] = "application/json"
            kwargs["json"] = payload
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + template, headers=headers, **kwargs)
        if not 200 <= response.status_code < 300:
            # Keep the provider's rejection words for connection evidence; remove
            # credentials if a server happens to echo the Authorization header.
            message = response.text[:2000].replace(credential.access_token, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": message or "Cradl AI request failed"}
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Cradl AI returned an invalid JSON response") from None
        if not isinstance(data, dict):
            raise ValueError("Cradl AI returned an invalid response object")
        if envelope:
            if not isinstance(data.get(envelope), list):
                raise ValueError("Cradl AI returned an invalid list envelope")
            token = data.get("nextToken")
            if token is not None and (not isinstance(token, str) or len(token) > 4096):
                raise ValueError("Cradl AI returned an invalid nextToken")
        return {"status": "success", "data": data, "http_status": response.status_code}
