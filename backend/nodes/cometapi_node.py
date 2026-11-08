"""CometAPI JSON APIs: one request per operation, with no automatic retries.

Generations consume provider credits. Task reads preserve the provider's status
and result URLs; a successful read does not assert that generation completed.
"""
from __future__ import annotations
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.cometapi.com"


class CometAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Cometapi API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://www.cometapi.com/console/token",
            "x-credential-instructions": "Create an API key in the CometAPI console and paste it without the Bearer prefix. Connecting reads this key's name and quota. Generation calls consume your CometAPI credits."})
    credential_type: Literal["cometapi_api_key"] = Field("cometapi_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetCurrentKey(_Input):
    """Get the connected API key's name, usage, quota and model limits."""
    operation: Literal["get_current_key"] = Field("get_current_key", json_schema_extra={"ui:hidden": True})


class ListModels(_Input):
    """List the public model catalog; it does not prove account access."""
    operation: Literal["list_models"] = Field("list_models", json_schema_extra={"ui:hidden": True})


class ChatMessage(_Input):
    role: Literal["system", "user", "assistant", "developer"]
    content: str = Field(..., min_length=1)


class CreateChatCompletion(_Input):
    """Create a non-streaming chat completion from text conversation history."""
    operation: Literal["create_chat_completion"] = Field("create_chat_completion", json_schema_extra={"ui:hidden": True})
    model: str = Field(..., min_length=1, description="CometAPI model ID from the model catalog.")
    messages: list[ChatMessage] = Field(..., min_length=1)
    max_completion_tokens: int | None = Field(None, ge=1)
    reasoning_effort: str | None = None
    temperature: float | None = Field(None, ge=0, le=2, description="Omit for models that do not support sampling overrides.")


class AnthropicMessage(_Input):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1)


class CreateMessage(_Input):
    """Create a non-streaming Anthropic-format text message."""
    operation: Literal["create_message"] = Field("create_message", json_schema_extra={"ui:hidden": True})
    model: str = Field(..., min_length=1)
    messages: list[AnthropicMessage] = Field(..., min_length=1)
    max_tokens: int = Field(..., ge=1)
    system: str | None = None


class Reasoning(_Input):
    effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"]


class CreateResponse(_Input):
    """Create a non-streaming model response from text input."""
    operation: Literal["create_response"] = Field("create_response", json_schema_extra={"ui:hidden": True})
    model: str = Field(..., min_length=1)
    input: str = Field(..., min_length=1, title="Input Text")
    instructions: str | None = None
    max_output_tokens: int | None = Field(None, ge=1)
    reasoning: Reasoning | None = None


class CreateEmbeddings(_Input):
    """Create numeric vectors for one text or a batch of texts."""
    operation: Literal["create_embeddings"] = Field("create_embeddings", json_schema_extra={"ui:hidden": True})
    model: str = Field(..., min_length=1)
    input: str | list[str] = Field(..., min_length=1, title="Text Input")
    dimensions: int | None = Field(None, ge=1)


class CreateModeration(_Input):
    """Classify text or a batch of texts for moderation."""
    operation: Literal["create_moderation"] = Field("create_moderation", json_schema_extra={"ui:hidden": True})
    model: str = Field("omni-moderation-latest")
    input: str | list[str] = Field(..., min_length=1, title="Text to Classify")


class CreateFluxImage(_Input):
    """Submit a FLUX image task; poll its ID with Get FLUX Result."""
    operation: Literal["create_flux_image"] = Field("create_flux_image", json_schema_extra={"ui:hidden": True})
    model: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", description="Native FLUX model ID, for example flux-2-pro.")
    prompt: str = Field(..., min_length=1)
    width: int | None = Field(None, ge=1)
    height: int | None = Field(None, ge=1)
    seed: int | None = None
    output_format: str | None = None


class _Task(_Input):
    task_id: str = Field(..., min_length=1, max_length=256, description="Task ID returned by the matching create operation.")

    @field_validator("task_id")
    @classmethod
    def identifier(cls, value):
        if value in {".", ".."} or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Use the task ID without whitespace or controls")
        return value


class GetFluxResult(_Task):
    """Read FLUX task status and the image URL when ready."""
    operation: Literal["get_flux_result"] = Field("get_flux_result", json_schema_extra={"ui:hidden": True})


class CreateMidjourneyImage(_Input):
    """Submit a Midjourney or Niji imagine task."""
    operation: Literal["create_midjourney_image"] = Field("create_midjourney_image", json_schema_extra={"ui:hidden": True})
    prompt: str = Field(..., min_length=1)
    botType: Literal["MID_JOURNEY", "NIJI_JOURNEY"] = Field("MID_JOURNEY", title="Bot Type")
    state: str | None = Field(None, description="Optional tracking value echoed by the provider.")


class GetMidjourneyTask(_Task):
    """Fetch Midjourney task status, progress, result URLs and buttons."""
    operation: Literal["get_midjourney_task"] = Field("get_midjourney_task", json_schema_extra={"ui:hidden": True})


class CreateRunwayVideo(_Input):
    """Submit a Runway Gen-4.5 text-to-video task."""
    operation: Literal["create_runway_video"] = Field("create_runway_video", json_schema_extra={"ui:hidden": True})
    model: Literal["gen4.5"] = "gen4.5"
    promptText: str = Field(..., min_length=1, max_length=1000, title="Prompt")
    ratio: Literal["1280:720", "720:1280"] = "1280:720"
    duration: int = Field(5, ge=2, le=10, description="Duration in whole seconds.")
    seed: int | None = Field(None, ge=0, le=4294967295)

    @field_validator("promptText")
    @classmethod
    def prompt_length(cls, value):
        if len(value.encode("utf-16-le")) // 2 > 1000:
            raise ValueError("Runway prompts support at most 1000 UTF-16 code units")
        return value


class GetRunwayTask(_Task):
    """Read Runway task status and output URLs when available."""
    operation: Literal["get_runway_task"] = Field("get_runway_task", json_schema_extra={"ui:hidden": True})


CometAPIConfig = Annotated[Union[GetCurrentKey, ListModels, CreateChatCompletion,
    CreateMessage, CreateResponse, CreateEmbeddings, CreateModeration,
    CreateFluxImage, GetFluxResult, CreateMidjourneyImage, GetMidjourneyTask,
    CreateRunwayVideo, GetRunwayTask], Field(discriminator="operation")]


class CometAPIFullConfig(NodeConfig[CometAPIConfig, CometAPIKeyCredential]):
    pass


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value


class CometAPINode(WorkflowNode):
    integration_type = "automation-cometapi"
    connection_evidence = ConnectionEvidence(noun="API key", identity_operation="get_current_key")

    @classmethod
    def get_config_model(cls):
        return CometAPIFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a CometAPI API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        body = op.model_dump(exclude={"operation"}, exclude_none=True)
        params = None
        headers = {"Authorization": "Bearer " + secret, "Accept": "application/json"}
        method = "POST"
        if isinstance(op, GetCurrentKey):
            method, path, body = "GET", "/api/usage/token", None
        elif isinstance(op, ListModels):
            method, path, body = "GET", "/api/models", None
        elif isinstance(op, CreateChatCompletion):
            path = "/v1/chat/completions"
            body["stream"] = False
        elif isinstance(op, CreateMessage):
            path = "/v1/messages"
            headers.pop("Authorization")
            headers["x-api-key"] = secret
            headers["anthropic-version"] = "2023-06-01"
            body["stream"] = False
        elif isinstance(op, CreateResponse):
            path = "/v1/responses"
            body["stream"] = False
        elif isinstance(op, CreateEmbeddings):
            path = "/v1/embeddings"
            body["encoding_format"] = "float"
        elif isinstance(op, CreateModeration):
            path = "/v1/moderations"
        elif isinstance(op, CreateFluxImage):
            path = "/flux/v1/" + quote(body.pop("model"), safe="")
            body["async"] = True
        elif isinstance(op, GetFluxResult):
            method, path, body, params = "GET", "/flux/v1/get_result", None, {"id": op.task_id}
        elif isinstance(op, CreateMidjourneyImage):
            path = "/mj/submit/imagine"
        elif isinstance(op, GetMidjourneyTask):
            method, path, body = "GET", "/mj/task/" + quote(op.task_id, safe="") + "/fetch", None
        elif isinstance(op, CreateRunwayVideo):
            path = "/runwayml/v1/text_to_video"
        elif isinstance(op, GetRunwayTask):
            method, path, body = "GET", "/runwayml/v1/tasks/" + quote(op.task_id, safe=""), None
        else:
            raise ValueError("Unsupported CometAPI operation")
        try:
            async with guarded_async_client(timeout=120, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, headers=headers, params=params, json=body)
        except httpx.HTTPError:
            raise ValueError("CometAPI request did not complete; check task history before retrying a generation") from None
        if not 200 <= response.status_code < 300:
            return {"status": "error", "http_status": response.status_code,
                "error": _redact(response.text[:1000], secret) or "CometAPI rejected the request"}
        if len(response.content) > 20_000_000:
            raise ValueError("CometAPI response exceeds the supported JSON size")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("CometAPI returned invalid JSON") from None
        if not isinstance(payload, dict):
            raise ValueError("CometAPI returned an unexpected JSON envelope")
        if payload.get("error") or payload.get("success") is False or payload.get("code") is False:
            return {"status": "error", "http_status": response.status_code, "error": _redact(payload, secret)}
        if isinstance(op, CreateMidjourneyImage) and payload.get("code") != 1:
            return {"status": "error", "error": _redact(payload, secret), "http_status": response.status_code}
        result = {"status": "success", "operation": op.operation, "data": _redact(payload, secret)}
        if isinstance(op, GetCurrentKey):
            key = payload.get("data")
            if payload.get("code") is not True or not isinstance(key, dict) or not isinstance(key.get("name"), str) or not key["name"]:
                raise ValueError("CometAPI key usage response did not identify this key")
            result["name"] = _redact(key["name"], secret)
        return result
