"""Langfuse Cloud project API: fixed public-contract operations with pasted keys.

Contract: https://cloud.langfuse.com/generated/api/openapi.yml
API and regional hosts: https://langfuse.com/docs/api-and-data-platform/features/public-api
"""
from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

FAMILY = "langfuse_api_key"
HOSTS = {
    "eu": "https://cloud.langfuse.com",
    "us": "https://us.cloud.langfuse.com",
    "jp": "https://jp.cloud.langfuse.com",
    "hipaa_us": "https://hipaa.cloud.langfuse.com",
}
JSON_EDITOR = {"ui:widget": "code_editor", "ui:language": "json"}


class LangfuseAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Langfuse API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://langfuse.com/docs/api-and-data-platform/features/public-api#obtain-credentials",
            "x-credential-instructions": "In your Langfuse project settings, create a project API key. Paste its public key and secret key, then select the project's Cloud region. Organization keys are not supported. NoClick uses Basic authentication to the selected Langfuse Cloud host. Self-hosted instances are not supported.",
        })
    credential_type: Literal["langfuse_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    public_key: str = Field(..., min_length=1, title="Public key", description="Project public API key from Langfuse project settings.", json_schema_extra={"ui:widget": "password"})
    secret_key: str = Field(..., min_length=1, title="Secret key", description="Secret API key paired with the public key.", json_schema_extra={"ui:widget": "password"})
    region: Literal["eu", "us", "jp", "hipaa_us"] = Field("eu", title="Cloud region", description="Use the region where your project lives.")

    @field_validator("public_key", "secret_key", mode="before")
    @classmethod
    def key(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() for c in value) or ":" in value or len(value) > 4096:
            raise ValueError("Paste the key alone, without spaces or an authorization header")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(Input):
    page: int = Field(1, ge=1, description="One-based page number. Fetch subsequent pages explicitly.")
    limit: int = Field(50, ge=1, le=100)


class ListProjects(Input):
    """Read the project associated with this project API key."""
    operation: Literal["list_projects"] = "list_projects"


class ListPrompts(Page):
    """List prompt metadata, versions and labels."""
    operation: Literal["list_prompts"] = "list_prompts"
    name: str | None = None
    label: str | None = None
    tag: str | None = None


class GetPrompt(Input):
    """Get a prompt, optionally selecting its version or label."""
    operation: Literal["get_prompt"] = "get_prompt"
    prompt_name: str = Field(..., min_length=1, max_length=255)
    version: int | None = Field(None, ge=1)
    label: str | None = None

    @model_validator(mode="after")
    def selector(self):
        if self.version is not None and self.label is not None:
            raise ValueError("Select either a prompt version or a label")
        return self


class CreateTextPrompt(Input):
    """Create a text prompt or a new version of an existing prompt."""
    operation: Literal["create_text_prompt"] = "create_text_prompt"
    name: str = Field(..., min_length=1, max_length=255)
    prompt: str = Field(..., description="Prompt template text, including Langfuse variables if needed.")
    commit_message: str | None = None


class UpdatePromptLabels(Input):
    """Replace a prompt version's deployment labels; labels move between versions."""
    operation: Literal["update_prompt_labels"] = "update_prompt_labels"
    name: str = Field(..., min_length=1, max_length=255)
    version: int = Field(..., ge=1)
    new_labels_json: str = Field("[]", description="JSON array of labels. Empty array removes labels; latest is reserved.", json_schema_extra=JSON_EDITOR)

    @field_validator("new_labels_json")
    @classmethod
    def labels(cls, value):
        labels = json.loads(value)
        if not isinstance(labels, list) or any(not isinstance(v, str) or not v or v == "latest" for v in labels):
            raise ValueError("Use a JSON array of nonempty labels other than latest")
        if len(set(labels)) != len(labels):
            raise ValueError("Labels must be unique")
        return value


class ListDatasets(Page):
    """List evaluation datasets."""
    operation: Literal["list_datasets"] = "list_datasets"


class GetDataset(Input):
    """Get dataset metadata by name."""
    operation: Literal["get_dataset"] = "get_dataset"
    dataset_name: str = Field(..., min_length=1)


class CreateDataset(Input):
    """Create an evaluation dataset."""
    operation: Literal["create_dataset"] = "create_dataset"
    name: str = Field(..., min_length=1)
    description: str | None = None


class ListDatasetItems(Page):
    """List dataset items, optionally filtering by dataset and source trace."""
    operation: Literal["list_dataset_items"] = "list_dataset_items"
    dataset_name: str | None = None
    source_trace_id: str | None = None


class GetDatasetItem(Input):
    """Get one dataset item."""
    operation: Literal["get_dataset_item"] = "get_dataset_item"
    item_id: str = Field(..., min_length=1, max_length=255)


class UpsertDatasetItem(Input):
    """Create an item or update the supplied project-unique item ID."""
    operation: Literal["upsert_dataset_item"] = "upsert_dataset_item"
    dataset_name: str = Field(..., min_length=1)
    item_id: str | None = Field(None, min_length=1, max_length=255)
    input_json: str = Field("null", description="Dataset input as JSON.", json_schema_extra=JSON_EDITOR)
    expected_output_json: str = Field("null", description="Expected output as JSON.", json_schema_extra=JSON_EDITOR)
    status: Literal["ACTIVE", "ARCHIVED"] = "ACTIVE"

    @field_validator("input_json", "expected_output_json")
    @classmethod
    def json_value(cls, value):
        json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Use finite JSON values")))
        return value


class DeleteDatasetItem(GetDatasetItem):
    """Irreversibly delete a dataset item and all its run items."""
    operation: Literal["delete_dataset_item"] = "delete_dataset_item"


class CursorPage(Input):
    limit: int = Field(50, ge=1, le=100)
    cursor: str | None = Field(None, description="Cursor returned in meta by the previous page, even if that page was empty.")


class ListObservations(CursorPage):
    """Read observation rows using the current v2 cursor API."""
    operation: Literal["list_observations"] = "list_observations"
    trace_id: str | None = None
    name: str | None = None
    from_start_time: str | None = Field(None, description="Inclusive ISO 8601 timestamp with timezone.")
    to_start_time: str | None = Field(None, description="Exclusive ISO 8601 timestamp with timezone.")

    @field_validator("from_start_time", "to_start_time")
    @classmethod
    def timestamp(cls, value):
        if value is not None and datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("Include a timezone")
        return value

    @model_validator(mode="after")
    def time_order(self):
        if self.from_start_time and self.to_start_time and datetime.fromisoformat(self.from_start_time.replace("Z", "+00:00")) >= datetime.fromisoformat(self.to_start_time.replace("Z", "+00:00")):
            raise ValueError("End time must follow start time")
        return self


class ListScores(CursorPage):
    """Read evaluation scores using the current v3 cursor API."""
    operation: Literal["list_scores"] = "list_scores"
    trace_id: str | None = None
    name: str | None = None


class CreateScore(Input):
    """Submit one numeric trace score for asynchronous processing."""
    operation: Literal["create_score"] = "create_score"
    trace_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    value: float = Field(..., allow_inf_nan=False)
    score_id: str | None = Field(None, min_length=1, description="Optional project-unique ID for the score.")
    comment: str | None = None


class DeleteScore(Input):
    """Delete a score by its Langfuse ID."""
    operation: Literal["delete_score"] = "delete_score"
    score_id: str = Field(..., min_length=1)


class ListComments(Page):
    """List comments in the project."""
    operation: Literal["list_comments"] = "list_comments"
    object_type: Literal["trace", "observation", "session", "prompt"] | None = None
    object_id: str | None = None

    @model_validator(mode="after")
    def object_filter(self):
        if self.object_id is not None and self.object_type is None:
            raise ValueError("Object ID also needs an object type")
        return self


class GetComment(Input):
    """Get a comment by ID."""
    operation: Literal["get_comment"] = "get_comment"
    comment_id: str = Field(..., min_length=1)


class CreateComment(Input):
    """Attach a comment to a trace, observation, session or prompt."""
    operation: Literal["create_comment"] = "create_comment"
    project_id: str = Field(..., min_length=1)
    object_type: Literal["trace", "observation", "session", "prompt"]
    object_id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1, max_length=5000)


LangfuseConfig = Annotated[Union[ListProjects, ListPrompts, GetPrompt, CreateTextPrompt, UpdatePromptLabels,
    ListDatasets, GetDataset, CreateDataset, ListDatasetItems, GetDatasetItem, UpsertDatasetItem,
    DeleteDatasetItem, ListObservations, ListScores, CreateScore, DeleteScore, ListComments, GetComment, CreateComment],
    Field(discriminator="operation")]


class LangfuseFullConfig(NodeConfig[LangfuseConfig, LangfuseAPIKeyCredential]):
    pass


# Each entry maps to exactly one operation in the pinned public API contract.
ROUTES = {
    "list_projects": ("GET", "/api/public/projects"),
    "list_prompts": ("GET", "/api/public/v2/prompts"),
    "get_prompt": ("GET", "/api/public/v2/prompts/{prompt_name}"),
    "create_text_prompt": ("POST", "/api/public/v2/prompts"),
    "update_prompt_labels": ("PATCH", "/api/public/v2/prompts/{name}/versions/{version}"),
    "list_datasets": ("GET", "/api/public/v2/datasets"),
    "get_dataset": ("GET", "/api/public/v2/datasets/{dataset_name}"),
    "create_dataset": ("POST", "/api/public/v2/datasets"),
    "list_dataset_items": ("GET", "/api/public/dataset-items"),
    "get_dataset_item": ("GET", "/api/public/dataset-items/{item_id}"),
    "upsert_dataset_item": ("POST", "/api/public/dataset-items"),
    "delete_dataset_item": ("DELETE", "/api/public/dataset-items/{item_id}"),
    "list_observations": ("GET", "/api/public/v2/observations"),
    "list_scores": ("GET", "/api/public/v3/scores"),
    "create_score": ("POST", "/api/public/scores"),
    "delete_score": ("DELETE", "/api/public/scores/{score_id}"),
    "list_comments": ("GET", "/api/public/comments"),
    "get_comment": ("GET", "/api/public/comments/{comment_id}"),
    "create_comment": ("POST", "/api/public/comments"),
}
ALIASES = {"dataset_name": "datasetName", "source_trace_id": "sourceTraceId", "trace_id": "traceId",
    "from_start_time": "fromStartTime", "to_start_time": "toStartTime", "object_type": "objectType",
    "object_id": "objectId", "project_id": "projectId", "commit_message": "commitMessage"}


def request_parts(config):
    method, path = ROUTES[config.operation]
    values = config.model_dump(exclude_none=True, exclude={"operation"})
    for name in list(values):
        if "{" + name + "}" in path:
            # Keep a name containing slashes within one encoded path parameter.
            encoded = quote(str(values.pop(name)), safe="")
            if encoded in {".", ".."} or any(ord(c) < 32 for c in encoded):
                raise ValueError("Use a resource identifier, not a path segment")
            path = path.replace("{" + name + "}", encoded)
    params, body = {}, None
    if method == "GET":
        params = {ALIASES.get(k, k): v for k, v in values.items()}
    elif method != "DELETE":
        body = {ALIASES.get(k, k): v for k, v in values.items()}
        if config.operation == "create_text_prompt":
            body["type"] = "text"
        elif config.operation == "update_prompt_labels":
            body = {"newLabels": json.loads(config.new_labels_json)}
        elif config.operation == "create_score":
            body["dataType"] = "NUMERIC"
            if "score_id" in body:
                body["id"] = body.pop("score_id")
            body = [body]
        elif config.operation == "upsert_dataset_item":
            body = {"datasetName": config.dataset_name, "input": json.loads(config.input_json),
                "expectedOutput": json.loads(config.expected_output_json), "status": config.status}
            if config.item_id is not None:
                body["id"] = config.item_id
    return method, path, params, body


class LangfuseNode(WorkflowNode):
    integration_type = "automation-langfuse"
    connection_evidence = ConnectionEvidence(noun="Langfuse project", operation="list_projects")

    @classmethod
    def get_config_model(cls):
        return LangfuseFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Langfuse project API key")
        method, path, params, body = request_parts(config)
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, HOSTS[credential.region] + path, params=params,
                    json=body, auth=httpx.BasicAuth(credential.public_key, credential.secret_key),
                    headers={"Accept": "application/json"})
        except httpx.HTTPError:
            return {"status": "error", "error": "Langfuse request could not be completed; inspect any write before retrying"}
        expected = 204 if config.operation == "delete_score" else 200
        # The published spec lists 200, while its endpoint description documents
        # 202 (accepted) and 207 (mixed acceptance). Neither means processing finished.
        allowed = {200, 202, 207} if config.operation == "create_score" else {expected}
        if response.status_code not in allowed:
            error = "Langfuse did not confirm the request; inspect any write before retrying"
            if response.status_code in {401, 403}:
                error = "Langfuse rejected the request"
                try:
                    rejection = response.json()
                    message = rejection.get("message") if isinstance(rejection, dict) else None
                    if isinstance(message, str) and message.strip():
                        error = message[:2000]
                        for secret in (credential.public_key, credential.secret_key,
                                base64.b64encode((credential.public_key + ":" + credential.secret_key).encode()).decode()):
                            error = error.replace(secret, "[redacted]")
                except ValueError:
                    pass
            return {"status": "error", "http_status": response.status_code, "error": error}
        if expected == 204:
            return {"status": "success", "http_status": 204, "deleted_id": config.score_id}
        try:
            if len(response.content) > 10_000_000:
                raise ValueError("Response exceeds size limit")
            data = response.json()
            if not isinstance(data, dict) or "error" in data or ("errors" in data and config.operation != "create_score"):
                raise ValueError("Invalid JSON response")
            if config.operation.startswith("list_"):
                if not isinstance(data.get("data"), list):
                    raise ValueError("Missing result list")
                if config.operation != "list_projects" and not isinstance(data.get("meta"), dict):
                    raise ValueError("Missing pagination metadata")
            elif config.operation == "create_score":
                if data.get("message") == "Accepted":
                    acceptance = "accepted"
                elif (type(data.get("accepted")) is int and data["accepted"] >= 0
                        and type(data.get("rejected")) is int and data["rejected"] >= 0
                        and isinstance(data.get("errors"), list)):
                    acceptance = "partial" if data["rejected"] and data["accepted"] else "error" if data["rejected"] else "accepted"
                else:
                    raise ValueError("Invalid score acceptance response")
                return {"status": acceptance, "data": data, "http_status": response.status_code,
                    "processing_complete": False, "retry_automatically": False}
            elif config.operation in {"get_prompt", "create_text_prompt", "update_prompt_labels"}:
                if not isinstance(data.get("name"), str) or type(data.get("version")) is not int or data.get("type") not in {"text", "chat"} or "prompt" not in data:
                    raise ValueError("Invalid prompt response")
            elif not isinstance(data.get("message" if config.operation == "delete_dataset_item" else "id"), str):
                raise ValueError("Missing result identifier")
        except (ValueError, TypeError):
            return {"status": "error", "http_status": response.status_code,
                "error": "Langfuse returned an unexpected response; inspect any write before retrying"}
        # Preserve provider data and pagination exactly, including empty cursor pages.
        if config.operation.startswith("list_"):
            return {**data, "status": "success", "http_status": response.status_code}
        return {"data": data, "status": "success", "http_status": response.status_code}
