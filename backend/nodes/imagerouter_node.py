"""ImageRouter's pinned OpenAPI 0.0.1: one provider request per action.

Public contract: https://api.imagerouter.io/.well-known/openapi.yaml
Normal account API keys only; management keys cannot generate media or read credits.
Media responses request hosted URLs (provider retention: 30 days).
Image transforms and animation use the provider-documented JSON image input:
https://docs.imagerouter.io/api-reference/image-generation
https://docs.imagerouter.io/api-reference/video-generation
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.imagerouter.io"


class ImagerouterAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="ImageRouter API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://imagerouter.io/api-keys",
            "x-credential-instructions": "Create a normal API key in ImageRouter's API Keys page and paste it below. Management keys are not supported. NoClick sends Bearer authentication to api.imagerouter.io and reads your account's credit usage by API key to verify the connection.",
        })
    credential_type: Literal["imagerouter_api_key"] = Field("imagerouter_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)

    @field_validator("image", "image_url", check_fields=False)
    @classmethod
    def image_reference(cls, value):
        if value.startswith("https://") or value.startswith("data:image/"):
            return value
        raise ValueError("Use an HTTPS image URL or an image data URI")


class _Generation(_Input):
    model: str = Field(..., min_length=1, description="Model ID from ImageRouter's model catalog, for example test/test for a dummy image.")
    prompt: str | None = Field(None, max_length=20000)
    response_format: Literal["url"] = Field("url", description="Hosted media URLs expire after 30 days. Save generated media elsewhere for long-term use.")
    size: str = Field("auto", description="Model-supported WIDTHxHEIGHT or auto.")


class _Image(_Generation):
    quality: Literal["auto", "low", "medium", "high", "very_low", "xhigh", "max"] = "auto"
    output_format: str | None = Field(None, description="Model-supported output format, e.g. webp, jpeg or png.")


class GenerateImage(_Image):
    """Generate an image from a text prompt."""
    operation: Literal["generate_image"] = Field("generate_image", json_schema_extra={"ui:hidden": True})


# The provider accepts HTTPS image URLs or image data URIs in JSON.
_IMAGE_INPUT = {"format": "uri"}


class GenerateImageFromImage(_Image):
    """Transform an image using the image-generation JSON endpoint."""
    operation: Literal["generate_image_from_image"] = Field("generate_image_from_image", json_schema_extra={"ui:hidden": True})
    image: str = Field(..., min_length=1, description="HTTPS image URL or image data URI.", json_schema_extra=_IMAGE_INPUT)


class _Video(_Generation):
    quality: Literal["auto", "low", "medium", "high"] = "auto"
    seconds: Union[Literal["auto"], Annotated[float, Field(ge=1, le=60)]] = Field("auto", description="Model-supported duration in seconds or auto.")


class GenerateVideo(_Video):
    """Generate a video from a text prompt."""
    operation: Literal["generate_video"] = Field("generate_video", json_schema_extra={"ui:hidden": True})


class GenerateVideoFromImage(_Video):
    """Animate an input image using JSON video generation."""
    operation: Literal["generate_video_from_image"] = Field("generate_video_from_image", json_schema_extra={"ui:hidden": True})
    image: str = Field(..., min_length=1, description="HTTPS image URL or image data URI.", json_schema_extra=_IMAGE_INPUT)


class Message(_Input):
    role: str = Field(..., min_length=1)
    content: Any = Field(None, description="Text or OpenAI-compatible multimodal content parts.")


class ChatCompletion(_Input):
    """Create a non-streaming chat completion with a text or multimodal model."""
    operation: Literal["create_chat_completion"] = Field("create_chat_completion", json_schema_extra={"ui:hidden": True})
    model: str = Field(..., min_length=1)
    messages: list[Message] = Field(..., min_length=1)


class DescribeImage(_Input):
    """Ask a vision-capable chat model about an image."""
    operation: Literal["describe_image"] = Field("describe_image", json_schema_extra={"ui:hidden": True})
    model: str = Field(..., min_length=1, description="A vision-capable model ID from ImageRouter.")
    prompt: str = Field(..., min_length=1, description="Question about the image.")
    image_url: str = Field(..., min_length=1, description="HTTPS image URL or image data URI.", json_schema_extra=_IMAGE_INPUT)


class ResponseInput(_Input):
    role: str | None = None
    content: Any = None


class CreateResponse(_Input):
    """Create a non-streaming response from text or structured input items."""
    operation: Literal["create_response"] = Field("create_response", json_schema_extra={"ui:hidden": True})
    model: str = Field(..., min_length=1)
    input: Union[str, list[ResponseInput]] = Field(..., description="Text prompt or OpenAI-compatible role/content input items.")


class ListModels(_Input):
    """List the legacy v1 model catalog from the pinned contract."""
    operation: Literal["list_models"] = Field("list_models", json_schema_extra={"ui:hidden": True})


class GetCredits(_Input):
    """Read the account's remaining credits, usage and total deposits."""
    operation: Literal["get_credits"] = Field("get_credits", json_schema_extra={"ui:hidden": True})


class ListAPIKeyUsage(_Input):
    """Read credit usage, spending limits and expiry broken down by API key."""
    operation: Literal["list_api_key_usage"] = Field("list_api_key_usage", json_schema_extra={"ui:hidden": True})


ImagerouterConfig = Annotated[Union[GenerateImage, GenerateImageFromImage, DescribeImage,
    GenerateVideo, GenerateVideoFromImage, ChatCompletion, CreateResponse, ListModels,
    GetCredits, ListAPIKeyUsage], Field(discriminator="operation")]


class ImagerouterFullConfig(NodeConfig[ImagerouterConfig, ImagerouterAPIKeyCredential]):
    pass


ROUTES = {
    "generate_image": ("POST", "/v1/openai/images/generations"),
    "generate_image_from_image": ("POST", "/v1/openai/images/generations"),
    "describe_image": ("POST", "/v1/openai/chat/completions"),
    "generate_video": ("POST", "/v1/openai/videos/generations"),
    "generate_video_from_image": ("POST", "/v1/openai/videos/generations"),
    "create_chat_completion": ("POST", "/v1/openai/chat/completions"),
    "create_response": ("POST", "/v1/openai/responses"),
    "list_models": ("GET", "/v1/models"),
    "get_credits": ("GET", "/v1/credits"),
    "list_api_key_usage": ("GET", "/v1/credits"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value


class ImagerouterNode(WorkflowNode):
    integration_type = "automation-imagerouter"
    connection_evidence = ConnectionEvidence(operation="list_api_key_usage", noun="API keys", label_keys=("api_key_name", "api_key_id"))

    @classmethod
    def get_config_model(cls):
        return ImagerouterFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an ImageRouter API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        kwargs = {"headers": {"Authorization": "Bearer " + key, "Accept": "application/json"}}
        if method == "GET":
            if config.operation == "list_api_key_usage":
                kwargs["params"] = {"by_api_key": "true"}
        elif config.operation == "describe_image":
            kwargs["json"] = {"model": config.model, "messages": [{"role": "user", "content": [
                {"type": "text", "text": config.prompt},
                {"type": "image_url", "image_url": {"url": config.image_url}},
            ]}]}
        else:
            kwargs["json"] = values
        # No automatic retries: a timeout may have generated and charged for media.
        try:
            async with guarded_async_client(timeout=180, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, **kwargs)
        except httpx.HTTPError:
            return {"status": "error", "error": "ImageRouter request could not be completed; check usage before retrying a generation"}
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            data = None
        if response.status_code != 200:
            message = json.dumps(data, ensure_ascii=False) if data is not None else response.text
            return {"status": "error", "status_code": response.status_code, "error": _redact(message, key)[:4000]}
        if not isinstance(data, (dict, list)) or isinstance(data, dict) and (data.get("error") or data.get("errors")):
            return {"status": "error", "error": _redact(json.dumps(data), key)[:4000] if data is not None else "ImageRouter returned an unexpected response"}
        if config.operation.startswith("generate_"):
            if not isinstance(data, dict) or not isinstance(data.get("data"), list) or not data["data"] or any(
                not isinstance(row, dict) or not isinstance(row.get("url"), str) or not row["url"].startswith("https://") or "b64_json" in row
                for row in data["data"]
            ):
                return {"status": "error", "error": "ImageRouter returned no hosted media URL"}
        if config.operation in {"get_credits", "list_api_key_usage"}:
            if not isinstance(data, dict) or any(not isinstance(data.get(k), str) for k in ("remaining_credits", "credit_usage", "total_deposits")):
                return {"status": "error", "error": "ImageRouter returned incomplete account credit information"}
            if config.operation == "list_api_key_usage" and (not isinstance(data.get("usage_by_api_key"), list) or any(not isinstance(row, dict) or not isinstance(row.get("api_key_name"), str) for row in data["usage_by_api_key"])):
                return {"status": "error", "error": "ImageRouter returned incomplete per-key usage information"}
        return {"status": "success", "http_status": response.status_code, "data": _redact(data, key)}
