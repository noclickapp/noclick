"""Baseten account, model, deployment, and inference workflow actions."""

from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

MANAGEMENT_API = "https://api.baseten.co/v1"
INFERENCE_API = "https://inference.baseten.co/v1"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_INPUT_CHARS = 100_000


class BasetenAPIKeyCredential(BaseModel):
    credential_type: Literal["baseten_api_key"] = Field(
        "baseten_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., title="API Key", min_length=1,
        description="Baseten API key from your workspace API Keys page.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(title="Baseten API Key", json_schema_extra={
        "x-credential-url": "https://app.baseten.co/settings/api_keys",
        "x-credential-instructions": "Create an API key in Baseten Settings → API Keys.",
    })


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _op(name: str, label: str, category: str) -> Any:
    return Field(
        name,
        json_schema_extra={
            "ui:hidden": True, "x-category": category, "x-display-name": label,
        },
    )


class BasetenCurrentUserConfig(_Operation):
    operation: Literal["get_current_user"] = _op("get_current_user", "Get Current User", "Account")


class BasetenListModelsConfig(_Operation):
    operation: Literal["list_models"] = _op("list_models", "List Models", "Models")
    name: str | None = Field(None, title="Exact Name", description="Optional exact model name filter.")
    max_results: int = Field(100, title="Max Results", ge=1, le=100)


class BasetenGetModelConfig(_Operation):
    operation: Literal["get_model"] = _op("get_model", "Get Model", "Models")
    model_id: str = Field(..., title="Model ID", min_length=1)


class BasetenListDeploymentsConfig(_Operation):
    operation: Literal["list_deployments"] = _op("list_deployments", "List Deployments", "Deployments")
    model_id: str = Field(..., title="Model ID", min_length=1)
    name: str | None = Field(None, title="Exact Name", description="Optional deployment name filter.")
    max_results: int = Field(100, title="Max Results", ge=1, le=100)


class BasetenGetDeploymentConfig(_Operation):
    operation: Literal["get_deployment"] = _op("get_deployment", "Get Deployment", "Deployments")
    model_id: str = Field(..., title="Model ID", min_length=1)
    deployment_id: str = Field(..., title="Deployment ID", min_length=1)


class BasetenListModelAPIsConfig(_Operation):
    operation: Literal["list_model_apis"] = _op("list_model_apis", "List Model APIs", "Model APIs")
    added_only: bool = Field(False, title="Added to Workspace Only")
    cursor: str | None = Field(None, title="Cursor", description="Opaque cursor from the previous page.")
    limit: int = Field(100, title="Limit", ge=1, le=1000)


class BasetenListInferenceModelsConfig(_Operation):
    operation: Literal["list_inference_models"] = _op(
        "list_inference_models", "List Inference Models", "Model APIs"
    )
    max_results: int = Field(100, title="Max Results", ge=1, le=100)


class BasetenChatCompletionConfig(_Operation):
    operation: Literal["chat_completion"] = _op(
        "chat_completion", "Create Chat Completion", "Inference"
    )
    model: str = Field(..., title="Model Slug", min_length=1,
                       description="A model slug returned by List Inference Models.")
    prompt: str = Field(..., title="Prompt", min_length=1, json_schema_extra={"ui:widget": "textarea"})
    system_prompt: str | None = Field(
        None, title="System Prompt", json_schema_extra={"ui:widget": "textarea"}
    )
    max_tokens: int | None = Field(None, title="Max Tokens", ge=1, le=8192)
    temperature: float | None = Field(None, title="Temperature", ge=0, le=2)


class BasetenPredictModelConfig(_Operation):
    operation: Literal["predict_model"] = _op("predict_model", "Predict with Model", "Inference")
    model_id: str = Field(..., title="Model ID", min_length=1)
    environment: str = Field(
        "production", title="Environment",
        description="Environment serving this model, usually production.",
    )
    input_json: str = Field(
        ..., title="Model Input (JSON)", min_length=1,
        description="JSON object or array matching your deployed model's input schema.",
        json_schema_extra={"ui:widget": "textarea"},
    )


class BasetenPredictDeploymentConfig(_Operation):
    operation: Literal["predict_deployment"] = _op(
        "predict_deployment", "Predict with Deployment", "Inference"
    )
    model_id: str = Field(..., title="Model ID", min_length=1)
    deployment_id: str = Field(..., title="Deployment ID", min_length=1)
    input_json: str = Field(
        ..., title="Model Input (JSON)", min_length=1,
        description="JSON object or array matching your deployed model's input schema.",
        json_schema_extra={"ui:widget": "textarea"},
    )


class BasetenAsyncPredictConfig(_Operation):
    operation: Literal["submit_async_prediction"] = _op(
        "submit_async_prediction", "Submit Async Prediction", "Inference"
    )
    model_id: str = Field(..., title="Model ID", min_length=1)
    environment: str = Field("production", title="Environment")
    input_json: str = Field(
        ..., title="Model Input (JSON)", min_length=1,
        description="JSON object matching your deployed model's input schema.",
        json_schema_extra={"ui:widget": "textarea"},
    )


class BasetenGetAsyncRequestConfig(_Operation):
    operation: Literal["get_async_request"] = _op(
        "get_async_request", "Get Async Request", "Inference"
    )
    model_id: str = Field(..., title="Model ID", min_length=1)
    request_id: str = Field(..., title="Request ID", min_length=1)


BasetenOperationConfig = Annotated[
    Union[
        BasetenCurrentUserConfig,
        BasetenListModelsConfig,
        BasetenGetModelConfig,
        BasetenListDeploymentsConfig,
        BasetenGetDeploymentConfig,
        BasetenListModelAPIsConfig,
        BasetenListInferenceModelsConfig,
        BasetenChatCompletionConfig,
        BasetenPredictModelConfig,
        BasetenPredictDeploymentConfig,
        BasetenAsyncPredictConfig,
        BasetenGetAsyncRequestConfig,
    ],
    Discriminator("operation"),
]


class BasetenNodeConfig(NodeConfig[BasetenOperationConfig, BasetenAPIKeyCredential]):
    model_config = ConfigDict(title="Baseten Node Configuration")


def _segment(value: str, label: str) -> str:
    if not _ID_RE.fullmatch(value.strip()):
        raise ValueError(f"{label} must contain only letters, numbers, hyphens, or underscores")
    return quote(value.strip(), safe="")


def _input_json(raw: str) -> dict[str, Any] | list[Any]:
    if len(raw) > _MAX_INPUT_CHARS:
        raise ValueError("Model input exceeds 100,000 characters")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Model input must be valid JSON") from exc
    if not isinstance(parsed, (dict, list)):
        raise ValueError("Model input must be a JSON object or array")
    return parsed


async def _request(
    api_key: str, method: str, url: str, *, action: str,
    params: dict[str, Any] | None = None, body: dict[str, Any] | list[Any] | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.request(
                method, url,
                headers={"Authorization": f"Bearer {api_key}"},
                params=params, json=body,
            )
        if response.status_code >= 400:
            # Provider errors can echo model input or credentials; keep only status.
            return {
                "status": "error", "action": action,
                "error": f"Baseten request failed (HTTP {response.status_code})",
                "status_code": response.status_code,
            }
        payload = response.json()
        return {"status": "success", "action": action, "data": payload,
                "status_code": response.status_code}
    except (httpx.HTTPError, ValueError):
        return {"status": "error", "action": action,
                "error": "Baseten request failed", "status_code": 0}


def _bounded_list(result: dict[str, Any], key: str, limit: int) -> dict[str, Any]:
    if result["status"] != "success":
        return result
    payload = result["data"]
    rows = payload.get(key, []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        raise ValueError(f"Baseten returned an invalid {key} list")
    result["data"] = {key: rows[:limit], "count": len(rows), "returned": min(len(rows), limit)}
    if isinstance(payload, dict) and "pagination" in payload:
        result["data"]["pagination"] = payload["pagination"]
    return result


class BasetenNode(WorkflowNode):
    integration_type = "automation-baseten"

    connection_evidence = ConnectionEvidence(
        identity_operation="get_current_user", noun="workspace",
        identity_keys=("workspace_name", "email", "user_id"),
    )

    @classmethod
    def get_config_model(cls):
        return BasetenNodeConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not self.config or not self.config.credentials:
            raise ValueError("Baseten API key is required")
        api_key = self.config.credentials.api_key
        cfg = self.config.config
        op = cfg.operation

        if op == "get_current_user":
            return await _request(api_key, "GET", f"{MANAGEMENT_API}/users/me", action=op)
        if op == "list_models":
            params = {"name": cfg.name} if cfg.name else None
            result = await _request(api_key, "GET", f"{MANAGEMENT_API}/models", action=op, params=params)
            return _bounded_list(result, "models", cfg.max_results)
        if op == "get_model":
            model_id = _segment(cfg.model_id, "Model ID")
            return await _request(api_key, "GET", f"{MANAGEMENT_API}/models/{model_id}", action=op)
        if op == "list_deployments":
            model_id = _segment(cfg.model_id, "Model ID")
            params = {"name": cfg.name} if cfg.name else None
            result = await _request(
                api_key, "GET", f"{MANAGEMENT_API}/models/{model_id}/deployments",
                action=op, params=params,
            )
            return _bounded_list(result, "deployments", cfg.max_results)
        if op == "get_deployment":
            model_id = _segment(cfg.model_id, "Model ID")
            deployment_id = _segment(cfg.deployment_id, "Deployment ID")
            return await _request(
                api_key, "GET", f"{MANAGEMENT_API}/models/{model_id}/deployments/{deployment_id}",
                action=op,
            )
        if op == "list_model_apis":
            params = {"limit": cfg.limit, "added_only": str(cfg.added_only).lower()}
            if cfg.cursor:
                params["cursor"] = cfg.cursor
            result = await _request(
                api_key, "GET", f"{MANAGEMENT_API}/model_apis", action=op, params=params,
            )
            return _bounded_list(result, "items", cfg.limit)
        if op == "list_inference_models":
            result = await _request(api_key, "GET", f"{INFERENCE_API}/models", action=op)
            return _bounded_list(result, "data", cfg.max_results)
        if op == "chat_completion":
            if len(cfg.prompt) > _MAX_INPUT_CHARS or len(cfg.system_prompt or "") > _MAX_INPUT_CHARS:
                raise ValueError("Chat prompt exceeds 100,000 characters")
            messages = []
            if cfg.system_prompt:
                messages.append({"role": "system", "content": cfg.system_prompt})
            messages.append({"role": "user", "content": cfg.prompt})
            body: dict[str, Any] = {"model": cfg.model, "messages": messages, "stream": False}
            if cfg.max_tokens is not None:
                body["max_tokens"] = cfg.max_tokens
            if cfg.temperature is not None:
                body["temperature"] = cfg.temperature
            result = await _request(
                api_key, "POST", f"{INFERENCE_API}/chat/completions", action=op,
                body=body, timeout=90,
            )
            if result["status"] == "success":
                data = result["data"]
                choices = data.get("choices") or []
                result["data"] = {
                    "id": data.get("id"), "model": data.get("model"),
                    "content": (choices[0].get("message") or {}).get("content") if choices else None,
                    "choices": choices, "usage": data.get("usage"),
                }
            return result
        if op in ("predict_model", "predict_deployment", "submit_async_prediction"):
            model_id = _segment(cfg.model_id, "Model ID")
            if op in ("predict_model", "submit_async_prediction"):
                target = f"environments/{_segment(cfg.environment, 'Environment')}"
            else:
                target = f"deployment/{_segment(cfg.deployment_id, 'Deployment ID')}"
            endpoint = "async_predict" if op == "submit_async_prediction" else "predict"
            url = f"https://model-{model_id}.api.baseten.co/{target}/{endpoint}"
            body = _input_json(cfg.input_json)
            if op == "submit_async_prediction":
                if not isinstance(body, dict):
                    raise ValueError("Async model input must be a JSON object")
                body = {"model_input": body}
            return await _request(
                api_key, "POST", url, action=op,
                body=body, timeout=120,
            )
        if op == "get_async_request":
            model_id = _segment(cfg.model_id, "Model ID")
            request_id = _segment(cfg.request_id, "Request ID")
            return await _request(
                api_key, "GET",
                f"https://model-{model_id}.api.baseten.co/async_request/{request_id}",
                action=op,
            )
        raise ValueError(f"Unsupported Baseten operation: {op}")
