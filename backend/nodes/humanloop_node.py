"""Humanloop v5 prompt, dataset and evaluation automation.

Contract: https://humanloop.com/docs/openapi/api.json (API 1.0.0).
Each operation issues exactly one documented request; pagination is explicit.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.humanloop.com/v5"


class HumanloopAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Humanloop API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://humanloop.com/docs/v5/guides/organization/manage-api-keys",
            "x-credential-instructions": "Create an API key in Humanloop organization settings, then paste it here. NoClick sends it to api.humanloop.com in the X-API-KEY header. Access is limited by the key's permissions.",
        },
    )
    credential_type: Literal["humanloop_api_key"] = Field("humanloop_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number; each run fetches one page.")
    size: int = Field(10, ge=1, le=100, description="Records per page.")


class _FileList(_Page):
    name: str | None = Field(None, description="Case-insensitive name filter.")
    user_filter: str | None = None
    sort_by: Literal["created_at", "updated_at", "name"] | None = None
    order: Literal["asc", "desc"] | None = None


class _Identified(_Input):
    id: str = Field(..., min_length=1, max_length=512, description="Humanloop resource ID.")

    @field_validator("id")
    @classmethod
    def identifier(cls, value):
        if value in {".", ".."} or any(c.isspace() or c in "/\\?#" or ord(c) < 32 for c in value):
            raise ValueError("Use a single Humanloop resource ID")
        return value


class _Versioned(_Identified):
    version_id: str | None = None
    environment: str | None = Field(None, description="Environment name. Leave version_id and environment unset for the deployed version.")


class ChatMessage(_Input):
    role: Literal["user", "assistant", "system", "tool", "developer"]
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None


class Datapoint(_Input):
    inputs: dict[str, str] | None = None
    messages: list[ChatMessage] | None = None
    target: dict[str, str | int | float | bool | list[Any] | dict[str, Any]] | None = None


class HumanloopListPromptsConfig(_FileList):
    """GET /prompts."""
    operation: Literal["list_prompts"] = Field("list_prompts", json_schema_extra={"ui:hidden": True})


class HumanloopGetPromptConfig(_Versioned):
    """GET /prompts/{id}."""
    operation: Literal["get_prompt"] = Field("get_prompt", json_schema_extra={"ui:hidden": True})


class HumanloopDeletePromptConfig(_Identified):
    """DELETE /prompts/{id}."""
    operation: Literal["delete_prompt"] = Field("delete_prompt", json_schema_extra={"ui:hidden": True})


class HumanloopMovePromptConfig(_Identified):
    """PATCH /prompts/{id}."""
    operation: Literal["move_prompt"] = Field("move_prompt", json_schema_extra={"ui:hidden": True})
    path: str = Field(..., min_length=1, description="New path including the file name.")


class HumanloopListDatasetsConfig(_FileList):
    """GET /datasets."""
    operation: Literal["list_datasets"] = Field("list_datasets", json_schema_extra={"ui:hidden": True})


class HumanloopGetDatasetConfig(_Versioned):
    """GET /datasets/{id}."""
    operation: Literal["get_dataset"] = Field("get_dataset", json_schema_extra={"ui:hidden": True})
    include_datapoints: bool | None = None


class HumanloopDeleteDatasetConfig(_Identified):
    """DELETE /datasets/{id}."""
    operation: Literal["delete_dataset"] = Field("delete_dataset", json_schema_extra={"ui:hidden": True})


class HumanloopMoveDatasetConfig(_Identified):
    """PATCH /datasets/{id}."""
    operation: Literal["move_dataset"] = Field("move_dataset", json_schema_extra={"ui:hidden": True})
    path: str = Field(..., min_length=1, description="New path including the file name.")


class HumanloopListEvaluatorsConfig(_FileList):
    """GET /evaluators."""
    operation: Literal["list_evaluators"] = Field("list_evaluators", json_schema_extra={"ui:hidden": True})


class HumanloopGetEvaluatorConfig(_Versioned):
    """GET /evaluators/{id}."""
    operation: Literal["get_evaluator"] = Field("get_evaluator", json_schema_extra={"ui:hidden": True})


class HumanloopDeleteEvaluatorConfig(_Identified):
    """DELETE /evaluators/{id}."""
    operation: Literal["delete_evaluator"] = Field("delete_evaluator", json_schema_extra={"ui:hidden": True})


class HumanloopUpsertPromptConfig(_Input):
    """POST /prompts."""
    operation: Literal["upsert_prompt"] = Field("upsert_prompt", json_schema_extra={"ui:hidden": True})
    path: str = Field(..., min_length=1, description="Prompt path including name; creates or versions this Prompt.")
    model: str = Field(..., min_length=1, description="Provider model name, such as gpt-4.")
    template: str | list[ChatMessage] | None = None
    endpoint: Literal["complete", "chat", "edit"] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    version_name: str | None = None
    version_description: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    attributes: dict[str, Any] | None = None


class HumanloopListPromptVersionsConfig(_Identified):
    """GET /prompts/{id}/versions."""
    operation: Literal["list_prompt_versions"] = Field("list_prompt_versions", json_schema_extra={"ui:hidden": True})
    evaluator_aggregates: bool | None = None


class HumanloopUpsertDatasetConfig(_Input):
    """POST /datasets."""
    operation: Literal["upsert_dataset"] = Field("upsert_dataset", json_schema_extra={"ui:hidden": True})
    path: str = Field(..., min_length=1, description="Dataset path including name; creates or versions this Dataset.")
    datapoints: list[Datapoint]
    action: Literal["set", "add", "remove"] | None = Field(None, description="set replaces the version's Datapoints; add appends; remove excludes matching Datapoints.")
    attributes: dict[str, Any] | None = None
    version_name: str | None = None
    version_description: str | None = None
    version_id: str | None = None
    environment: str | None = None
    include_datapoints: bool | None = None


class HumanloopListDatapointsConfig(_Versioned):
    """GET /datasets/{id}/datapoints."""
    operation: Literal["list_datapoints"] = Field("list_datapoints", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    size: int = Field(10, ge=1, le=100)


class HumanloopListEvaluationsConfig(_Page):
    """GET /evaluations."""
    operation: Literal["list_evaluations"] = Field("list_evaluations", json_schema_extra={"ui:hidden": True})
    file_id: str = Field(..., min_length=1)


class HumanloopGetEvaluationConfig(_Identified):
    """GET /evaluations/{id}."""
    operation: Literal["get_evaluation"] = Field("get_evaluation", json_schema_extra={"ui:hidden": True})


class HumanloopDeleteEvaluationConfig(_Identified):
    """DELETE /evaluations/{id}."""
    operation: Literal["delete_evaluation"] = Field("delete_evaluation", json_schema_extra={"ui:hidden": True})


class HumanloopListLogsConfig(_Page):
    """GET /logs."""
    operation: Literal["list_logs"] = Field("list_logs", json_schema_extra={"ui:hidden": True})
    file_id: str = Field(..., min_length=1)
    version_id: str | None = None
    search: str | None = None


class HumanloopGetLogConfig(_Identified):
    """GET /logs/{id}."""
    operation: Literal["get_log"] = Field("get_log", json_schema_extra={"ui:hidden": True})


class HumanloopListDirectoriesConfig(_Input):
    """GET /directories."""
    operation: Literal["list_directories"] = Field("list_directories", json_schema_extra={"ui:hidden": True})


class HumanloopGetDirectoryConfig(_Identified):
    """GET /directories/{id}."""
    operation: Literal["get_directory"] = Field("get_directory", json_schema_extra={"ui:hidden": True})


class HumanloopCreateDirectoryConfig(_Input):
    """POST /directories."""
    operation: Literal["create_directory"] = Field("create_directory", json_schema_extra={"ui:hidden": True})
    path: str = Field(..., min_length=1, description="Directory path including name.")


class HumanloopUpdateDirectoryConfig(_Identified):
    """PATCH /directories/{id}."""
    operation: Literal["update_directory"] = Field("update_directory", json_schema_extra={"ui:hidden": True})
    path: str = Field(..., min_length=1, description="New directory path including name.")


class HumanloopDeleteDirectoryConfig(_Identified):
    """DELETE /directories/{id}."""
    operation: Literal["delete_directory"] = Field("delete_directory", json_schema_extra={"ui:hidden": True})


HumanloopConfig = Annotated[Union[
    HumanloopListPromptsConfig,
    HumanloopGetPromptConfig,
    HumanloopDeletePromptConfig,
    HumanloopMovePromptConfig,
    HumanloopListDatasetsConfig,
    HumanloopGetDatasetConfig,
    HumanloopDeleteDatasetConfig,
    HumanloopMoveDatasetConfig,
    HumanloopListEvaluatorsConfig,
    HumanloopGetEvaluatorConfig,
    HumanloopDeleteEvaluatorConfig,
    HumanloopUpsertPromptConfig,
    HumanloopListPromptVersionsConfig,
    HumanloopUpsertDatasetConfig,
    HumanloopListDatapointsConfig,
    HumanloopListEvaluationsConfig,
    HumanloopGetEvaluationConfig,
    HumanloopDeleteEvaluationConfig,
    HumanloopListLogsConfig,
    HumanloopGetLogConfig,
    HumanloopListDirectoriesConfig,
    HumanloopGetDirectoryConfig,
    HumanloopCreateDirectoryConfig,
    HumanloopUpdateDirectoryConfig,
    HumanloopDeleteDirectoryConfig,
], Field(discriminator="operation")]


class HumanloopNodeConfig(NodeConfig[HumanloopConfig, HumanloopAPIKeyCredential]):
    pass


# Fixed operations from the pinned contract; no arbitrary URL, method or body.
OPERATIONS = {
    "list_prompts": ('GET', '/prompts', ('page', 'size', 'name', 'user_filter', 'sort_by', 'order'), 'page'),
    "get_prompt": ('GET', '/prompts/{id}', ('version_id', 'environment'), 'object'),
    "delete_prompt": ('DELETE', '/prompts/{id}', (), 'empty'),
    "move_prompt": ('PATCH', '/prompts/{id}', (), 'object'),
    "list_datasets": ('GET', '/datasets', ('page', 'size', 'name', 'user_filter', 'sort_by', 'order'), 'page'),
    "get_dataset": ('GET', '/datasets/{id}', ('version_id', 'environment', 'include_datapoints'), 'object'),
    "delete_dataset": ('DELETE', '/datasets/{id}', (), 'empty'),
    "move_dataset": ('PATCH', '/datasets/{id}', (), 'object'),
    "list_evaluators": ('GET', '/evaluators', ('page', 'size', 'name', 'user_filter', 'sort_by', 'order'), 'page'),
    "get_evaluator": ('GET', '/evaluators/{id}', ('version_id', 'environment'), 'object'),
    "delete_evaluator": ('DELETE', '/evaluators/{id}', (), 'empty'),
    "upsert_prompt": ('POST', '/prompts', (), 'object'),
    "list_prompt_versions": ('GET', '/prompts/{id}/versions', ('evaluator_aggregates',), 'records'),
    "upsert_dataset": ('POST', '/datasets', ('version_id', 'environment', 'include_datapoints'), 'object'),
    "list_datapoints": ('GET', '/datasets/{id}/datapoints', ('version_id', 'environment', 'page', 'size'), 'page'),
    "list_evaluations": ('GET', '/evaluations', ('file_id', 'page', 'size'), 'page'),
    "get_evaluation": ('GET', '/evaluations/{id}', (), 'object'),
    "delete_evaluation": ('DELETE', '/evaluations/{id}', (), 'empty'),
    "list_logs": ('GET', '/logs', ('file_id', 'page', 'size', 'version_id', 'search'), 'page'),
    "get_log": ('GET', '/logs/{id}', (), 'object'),
    "list_directories": ('GET', '/directories', (), 'array'),
    "get_directory": ('GET', '/directories/{id}', (), 'object'),
    "create_directory": ('POST', '/directories', (), 'object'),
    "update_directory": ('PATCH', '/directories/{id}', (), 'object'),
    "delete_directory": ('DELETE', '/directories/{id}', (), 'empty'),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {str(k).replace(secret, "[redacted]"): _redact(v, secret) for k, v in value.items()}
    return value


class HumanloopNode(WorkflowNode):
    integration_type = "automation-humanloop"
    connection_evidence = ConnectionEvidence(noun="prompts", operation="list_prompts", label_keys=("name", "path", "id"))

    @classmethod
    def get_config_model(cls):
        return HumanloopNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Humanloop API key")
        config = self.config.config
        secret = self.config.credentials.api_key
        method, route, query_keys, kind = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        if "{id}" in route:
            route = route.replace("{id}", quote(values.pop("id"), safe=""))
        params = {key: values.pop(key) for key in query_keys if key in values}
        body = values if method in {"POST", "PATCH"} else None
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route,
                    headers={"X-API-KEY": secret, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
        except (httpx.TransportError, TimeoutError):
            # A failed write transport may have reached the server. Never retry automatically.
            raise ValueError("Humanloop request could not be confirmed; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            message = _redact(response.text[:2000], secret)
            raise ValueError(f"Humanloop HTTP {response.status_code}: {message}") from None
        if kind == "empty":
            output = {"status": "success", "http_status": response.status_code, "acknowledged": True}
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Humanloop returned invalid JSON; inspect writes before retrying") from None
            if kind == "array":
                if not isinstance(data, list):
                    raise ValueError("Humanloop directory list must be an array")
                output = {"status": "success", "data": data}
            elif kind in {"page", "records"}:
                if not isinstance(data, dict) or not isinstance(data.get("records"), list):
                    raise ValueError("Humanloop list response is missing records")
                output = {"status": "success", "data": data["records"]}
                if kind == "page":
                    if any(type(data.get(key)) is not int for key in ("page", "size", "total")):
                        raise ValueError("Humanloop pagination metadata is invalid")
                    page, size, total = data["page"], data["size"], data["total"]
                    if page < 1 or size < 0 or total < 0:
                        raise ValueError("Humanloop pagination metadata is invalid")
                    more = page * size < total and size > 0
                    output.update(page=page, size=size, total=total, has_more=more,
                                  next_page=page + 1 if more else None)
            else:
                if not isinstance(data, dict):
                    raise ValueError("Humanloop resource response must be an object")
                output = {"status": "success", "data": data}
            output["http_status"] = response.status_code
        output = _redact(output, secret)
        await self.emit(output)
        return output
