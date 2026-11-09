"""Scale AI's Launch API: model deployments, inference and fine-tuning.

Contract: https://raw.githubusercontent.com/scaleapi/launch-python-client/master/openapi.json
The official SDK's launch/constants.py and LaunchClient.__init__ establish the
host prefix and API-key-as-Basic-username authentication respectively.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.scale.com/v1/launch"
TYPE = "scale_ai_api_key"
RESOURCE = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$"


class ScaleAiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Scale AI API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.scale.com/apikeys",
            "x-credential-instructions": "Paste your Scale API key with access to Launch. NoClick sends it as the HTTP Basic username with an empty password to api.scale.com. Listing your model endpoints verifies the connection.",
        },
    )
    credential_type: Literal["scale_ai_api_key"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API key as text")
        value = clean_secret(value, field_name="API key", key=True)
        if ":" in value or any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header prefix or colon")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def path_segment(cls, value, info):
        if info.field_name in {"model_bundle_id", "model_endpoint_id", "task_id", "fine_tune_id", "file_id"} and value in {".", ".."}:
            raise ValueError("Use a resource ID, not a path segment")
        return value


class ListModelBundles(_Input):
    """List model bundles owned by the connected account."""
    operation: Literal["list_model_bundles"] = "list_model_bundles"
    model_name: str | None = None
    order_by: Literal["newest", "oldest"] | None = None


class GetModelBundle(_Input):
    """Read a model bundle's deployment metadata."""
    operation: Literal["get_model_bundle"] = "get_model_bundle"
    model_bundle_id: str = Field(..., pattern=RESOURCE)


class GetLatestModelBundle(_Input):
    """Find the latest bundle for a model name."""
    operation: Literal["get_latest_model_bundle"] = "get_latest_model_bundle"
    model_name: str = Field(..., min_length=1)


class ListModelEndpoints(_Input):
    """List model deployments owned by the connected account."""
    operation: Literal["list_model_endpoints"] = "list_model_endpoints"
    name: str | None = None
    order_by: Literal["newest", "oldest", "alphabetical"] | None = None


class _Endpoint(_Input):
    model_endpoint_id: str = Field(..., pattern=RESOURCE)


class GetModelEndpoint(_Endpoint):
    """Read one model endpoint's configuration and status."""
    operation: Literal["get_model_endpoint"] = "get_model_endpoint"


class _Compute(_Input):
    model_bundle_id: str | None = Field(None, pattern=RESOURCE)
    cpus: str | int | float | None = Field(None, description="CPU quantity, for example 1 or 500m.")
    gpus: int | None = Field(None, ge=0)
    gpu_type: Literal["nvidia-tesla-t4", "nvidia-ampere-a10", "nvidia-ampere-a100", "nvidia-ampere-a100e", "nvidia-hopper-h100", "nvidia-hopper-h100-1g20gb", "nvidia-hopper-h100-3g40gb"] | None = None
    memory: str | int | float | None = Field(None, description="Memory quantity, for example 4Gi.")
    storage: str | int | float | None = Field(None, description="Storage quantity, for example 10Gi.")
    min_workers: int | None = Field(None, ge=0)
    max_workers: int | None = Field(None, ge=0)
    per_worker: int | None = Field(None, gt=0)
    labels: dict[str, str] | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def workers(self):
        if self.min_workers is not None and self.max_workers is not None and self.min_workers > self.max_workers:
            raise ValueError("Maximum workers must be at least minimum workers")
        return self


class CreateModelEndpoint(_Compute):
    """Deploy a bundle on provisioned workers. This allocates paid compute."""
    operation: Literal["create_model_endpoint"] = "create_model_endpoint"
    name: str = Field(..., min_length=1, max_length=63)
    model_bundle_id: str = Field(..., pattern=RESOURCE)
    endpoint_type: Literal["async", "sync", "streaming"]
    cpus: str | int | float
    gpus: int = Field(0, ge=0)
    memory: str | int | float
    storage: str | int | float
    min_workers: int = Field(..., ge=0)
    max_workers: int = Field(..., ge=0)
    per_worker: int = Field(..., gt=0)
    labels: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def sync_workers(self):
        # Official Launch getting-started guide: a synchronous endpoint must
        # always have at least one worker to serve blocking inference calls.
        if self.endpoint_type == "sync" and self.min_workers < 1:
            raise ValueError("Synchronous endpoints require at least one minimum worker")
        return self


class UpdateModelEndpoint(_Compute, _Endpoint):
    """Change a deployment's bundle, compute settings, labels or metadata."""
    operation: Literal["update_model_endpoint"] = "update_model_endpoint"

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "model_endpoint_id"}):
            raise ValueError("Supply at least one endpoint setting to update")
        return self


class DeleteModelEndpoint(_Endpoint):
    """Delete a model deployment and stop its workers."""
    operation: Literal["delete_model_endpoint"] = "delete_model_endpoint"


class RestartModelEndpoint(_Endpoint):
    """Restart the workers serving a model deployment."""
    operation: Literal["restart_model_endpoint"] = "restart_model_endpoint"


class CreateAsyncTask(_Endpoint):
    """Submit JSON model inputs for asynchronous inference."""
    operation: Literal["create_async_task"] = "create_async_task"
    args: dict[str, Any] | list[Any] | str | int | float | bool = Field(..., description="JSON input in the deployed model's request format.")


class GetAsyncTask(_Input):
    """Poll asynchronous inference status and retrieve the JSON result."""
    operation: Literal["get_async_task"] = "get_async_task"
    task_id: str = Field(..., pattern=RESOURCE)


class CreateSyncTask(_Endpoint):
    """Run synchronous inference with JSON model inputs."""
    operation: Literal["create_sync_task"] = "create_sync_task"
    args: dict[str, Any] | list[Any] | str | int | float | bool = Field(..., description="JSON input in the deployed model's request format.")
    timeout_seconds: float | None = Field(None, gt=0)
    num_retries: int | None = Field(None, ge=0, description="Provider-side inference retries; NoClick does not retry the HTTP request.")


class ListFineTunes(_Input):
    """List the connected account's fine-tuning jobs."""
    operation: Literal["list_fine_tunes"] = "list_fine_tunes"


class _FineTune(_Input):
    fine_tune_id: str = Field(..., pattern=RESOURCE)


class CreateFineTune(_Input):
    """Start a paid fine-tuning job using an existing training file."""
    operation: Literal["create_fine_tune"] = "create_fine_tune"
    model: str = Field(..., min_length=1)
    training_file: str = Field(..., min_length=1)
    validation_file: str | None = None
    hyperparameters: dict[str, str | int | float | dict[str, Any]] = Field(default_factory=dict)
    suffix: str | None = None


class GetFineTune(_FineTune):
    """Read fine-tuning progress and the resulting model name."""
    operation: Literal["get_fine_tune"] = "get_fine_tune"


class CancelFineTune(_FineTune):
    """Cancel a fine-tuning job."""
    operation: Literal["cancel_fine_tune"] = "cancel_fine_tune"


class GetFineTuneEvents(_FineTune):
    """Read a fine-tuning job's progress events."""
    operation: Literal["get_fine_tune_events"] = "get_fine_tune_events"


class ListFiles(_Input):
    """List file IDs, names and sizes for the connected account."""
    operation: Literal["list_files"] = "list_files"


class _File(_Input):
    file_id: str = Field(..., pattern=RESOURCE)


class GetFile(_File):
    """Read file metadata without downloading file contents."""
    operation: Literal["get_file"] = "get_file"


class DeleteFile(_File):
    """Delete a stored file."""
    operation: Literal["delete_file"] = "delete_file"


Operation = Annotated[Union[
    ListModelBundles, GetModelBundle, GetLatestModelBundle,
    ListModelEndpoints, GetModelEndpoint, CreateModelEndpoint, UpdateModelEndpoint,
    DeleteModelEndpoint, RestartModelEndpoint, CreateAsyncTask, GetAsyncTask, CreateSyncTask,
    ListFineTunes, CreateFineTune, GetFineTune, CancelFineTune, GetFineTuneEvents,
    ListFiles, GetFile, DeleteFile,
], Field(discriminator="operation")]


class ScaleAiNodeConfig(NodeConfig[Operation, ScaleAiAPIKeyCredential]):
    pass


# Each action makes exactly one published API operation. Query names are kept
# separate from path parameters so inference endpoint IDs are sent in the query.
ROUTES = {
    "list_model_bundles": ("GET", "/v1/model-bundles", ("model_name", "order_by")),
    "get_model_bundle": ("GET", "/v1/model-bundles/{model_bundle_id}", ()),
    "get_latest_model_bundle": ("GET", "/v1/model-bundles/latest", ("model_name",)),
    "list_model_endpoints": ("GET", "/v1/model-endpoints", ("name", "order_by")),
    "get_model_endpoint": ("GET", "/v1/model-endpoints/{model_endpoint_id}", ()),
    "create_model_endpoint": ("POST", "/v1/model-endpoints", ()),
    "update_model_endpoint": ("PUT", "/v1/model-endpoints/{model_endpoint_id}", ()),
    "delete_model_endpoint": ("DELETE", "/v1/model-endpoints/{model_endpoint_id}", ()),
    "restart_model_endpoint": ("POST", "/v1/model-endpoints/{model_endpoint_id}/restart", ()),
    "create_async_task": ("POST", "/v1/async-tasks", ("model_endpoint_id",)),
    "get_async_task": ("GET", "/v1/async-tasks/{task_id}", ()),
    "create_sync_task": ("POST", "/v1/sync-tasks", ("model_endpoint_id",)),
    "list_fine_tunes": ("GET", "/v1/llm/fine-tunes", ()),
    "create_fine_tune": ("POST", "/v1/llm/fine-tunes", ()),
    "get_fine_tune": ("GET", "/v1/llm/fine-tunes/{fine_tune_id}", ()),
    "cancel_fine_tune": ("PUT", "/v1/llm/fine-tunes/{fine_tune_id}/cancel", ()),
    "get_fine_tune_events": ("GET", "/v1/llm/fine-tunes/{fine_tune_id}/events", ()),
    "list_files": ("GET", "/v1/files", ()),
    "get_file": ("GET", "/v1/files/{file_id}", ()),
    "delete_file": ("DELETE", "/v1/files/{file_id}", ()),
}


class ScaleAiNode(WorkflowNode):
    integration_type = "automation-scale-ai"
    connection_evidence = ConnectionEvidence(noun="model endpoints", operation="list_model_endpoints")

    @classmethod
    def get_config_model(cls):
        return ScaleAiNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if isinstance(raw, dict) and "credential_type" in raw and raw["credential_type"] != TYPE:
            raise ValueError("Connect a Scale AI API key")
        return super().parse_config(config_data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Scale AI API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, template, query_names = ROUTES[config.operation]
        values = config.model_dump(exclude={"operation"}, exclude_none=True)
        path = template
        for name in tuple(values):
            if "{" + name + "}" in template:
                path = path.replace("{" + name + "}", values.pop(name))
        params = {name: values.pop(name) for name in query_names if name in values}
        kwargs = {"params": params}
        if method in {"POST", "PUT"} and values:
            kwargs["json"] = values
        try:
            async with guarded_async_client(timeout=120.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, auth=httpx.BasicAuth(key, ""),
                                                headers={"Accept": "application/json"}, **kwargs)
            # Keep the provider's rejection message for the connect evidence seam.
            if not 200 <= response.status_code < 300:
                output = {"status": "error", "success": False, "status_code": response.status_code,
                          "error": response.text.replace(key, "[redacted]")[:2000]}
            else:
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Scale AI returned an unexpected JSON representation")
                if data.get("error") or data.get("errors") or data.get("success") is False:
                    output = {"status": "error", "success": False, "error": data}
                else:
                    _validate_response(config.operation, data)
                    output = {"status": "success", "success": True, "data": data}
        except httpx.RequestError:
            raise ValueError("Scale AI could not be reached; the request outcome is unverified") from None
        await self.emit(output)
        return output


def _validate_response(operation, data):
    """Reject malformed successes, especially before accepting a pasted key."""
    lists = {"list_model_bundles": "model_bundles", "list_model_endpoints": "model_endpoints",
             "list_fine_tunes": "jobs", "get_fine_tune_events": "events", "list_files": "files"}
    if operation in lists:
        rows = data.get(lists[operation])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("Scale AI returned an unexpected collection")
        if operation == "list_model_endpoints" and any(not isinstance(row.get("id"), str) or not isinstance(row.get("name"), str) for row in rows):
            raise ValueError("Scale AI returned an unexpected model endpoint")
    required = {
        "get_model_bundle": ("id", "name"), "get_latest_model_bundle": ("id", "name"),
        "get_model_endpoint": ("id", "name"), "create_model_endpoint": ("endpoint_creation_task_id",),
        "update_model_endpoint": ("endpoint_creation_task_id",), "create_async_task": ("task_id",),
        "get_async_task": ("task_id", "status"), "create_sync_task": ("status",),
        "create_fine_tune": ("id",), "get_fine_tune": ("id", "status"), "get_file": ("id", "filename"),
    }
    if any(not isinstance(data.get(name), str) for name in required.get(operation, ())):
        raise ValueError("Scale AI returned an unexpected resource")
    for action, flag in {"delete_model_endpoint": "deleted", "delete_file": "deleted", "restart_model_endpoint": "restarted", "cancel_fine_tune": "success"}.items():
        if operation == action and data.get(flag) is not True:
            raise ValueError("Scale AI did not confirm the requested action")
