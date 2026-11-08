"""Deepimage image processing API. Each action makes one documented API call.

Processing submission acknowledges a job, not completion. Read get_result later;
process_image_wait may also return a pending job after the provider's 25s wait.
Contract: https://documentation.deep-image.ai/api-docs
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://deep-image.ai/rest_api"

class DeepimageAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Deepimage API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://deep-image.ai/app/my-profile/api",
        "x-credential-instructions": "Paste your Deepimage API key from your account's API page. Processing uses your Deepimage credits. NoClick verifies the key by reading your account profile."})
    credential_type: Literal["deepimage_api_key"] = Field("deepimage_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header")
        return value

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class GetAccount(Input):
    operation: Literal["get_account"] = "get_account"

class GetResult(Input):
    operation: Literal["get_result"] = "get_result"
    job_hash: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$", description="Job hash returned by a processing action.")

class DeleteResult(GetResult):
    operation: Literal["delete_result"] = "delete_result"

class ImageInput(Input):
    image_url: str = Field(..., min_length=1, description="Public HTTPS image URL. Deepimage fetches this image; NoClick does not download it.")
    output_format: Literal["jpeg", "png", "webp"] | None = None
    quality: int | None = Field(None, ge=0, le=100, description="JPEG or WebP compression quality.")

    @field_validator("image_url")
    @classmethod
    def url(cls, value):
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or any(c.isspace() for c in value):
            raise ValueError("Use a public HTTPS image URL")
        return value

class ResizeInput(ImageInput):
    width: int = Field(..., gt=0, description="Output width in pixels; height is calculated proportionally when omitted.")
    height: int | None = Field(None, gt=0)
    fit: Literal["canvas", "bounds", "cover", "crop"] | None = None

class ProcessImage(ResizeInput):
    operation: Literal["process_image"] = "process_image"
    enhancements: list[Literal["denoise", "deblur", "light", "color", "white_balance"]] = Field(default_factory=list)

class ProcessImageWait(ProcessImage):
    """Wait up to the provider's 25 second processing window; a pending job remains possible."""
    operation: Literal["process_image_wait"] = "process_image_wait"

class UpscaleImage(ResizeInput):
    operation: Literal["upscale_image"] = "upscale_image"

class DenoiseImage(ImageInput):
    operation: Literal["denoise_image"] = "denoise_image"

class DeblurImage(ImageInput):
    operation: Literal["deblur_image"] = "deblur_image"

class EnhanceLighting(ImageInput):
    operation: Literal["enhance_lighting"] = "enhance_lighting"

class EnhanceColors(ImageInput):
    operation: Literal["enhance_colors"] = "enhance_colors"

class CorrectWhiteBalance(ImageInput):
    operation: Literal["correct_white_balance"] = "correct_white_balance"

class RemoveBackground(ImageInput):
    operation: Literal["remove_background"] = "remove_background"
    remove: Literal["auto", "human", "item"] = "auto"

class ReplaceBackground(RemoveBackground):
    operation: Literal["replace_background"] = "replace_background"
    background_url: str = Field(..., min_length=1, description="Public HTTPS replacement background image URL.")
    _background_url = field_validator("background_url")(ImageInput.url.__func__)

class GenerateImage(Input):
    operation: Literal["generate_image"] = "generate_image"
    description: str = Field(..., min_length=1, max_length=10000, description="Describe the image to generate.")

DeepimageOperation = Annotated[Union[GetAccount, GetResult, DeleteResult, ProcessImage, ProcessImageWait, UpscaleImage,
    DenoiseImage, DeblurImage, EnhanceLighting, EnhanceColors, CorrectWhiteBalance, RemoveBackground, ReplaceBackground, GenerateImage], Field(discriminator="operation")]

class DeepimageConfig(NodeConfig[DeepimageOperation, DeepimageAPIKeyCredential]):
    pass

ENHANCEMENTS = {
    "denoise_image": "denoise", "deblur_image": "deblur", "enhance_lighting": "light",
    "enhance_colors": "color", "correct_white_balance": "white_balance",
}

def request_for(config):
    action = config.operation
    if action == "get_account":
        return "GET", "/me", None
    if action in {"get_result", "delete_result"}:
        return "GET" if action == "get_result" else "DELETE", "/result/" + quote(config.job_hash, safe=""), None
    if action == "generate_image":
        body = {"background": {"generate": {"description": config.description}}}
    else:
        body = {"url": config.image_url}
        for key in ("width", "height", "fit", "output_format", "quality", "enhancements"):
            value = getattr(config, key, None)
            if value is not None and value != []:
                body[key] = value
        if action in ENHANCEMENTS:
            body["enhancements"] = [ENHANCEMENTS[action]]
        if action in {"remove_background", "replace_background"}:
            body["background"] = {"remove": config.remove}
            if action == "replace_background":
                body["background"]["replace"] = config.background_url
    return "POST", "/process_result" if action == "process_image_wait" else "/process", body

class DeepimageNode(WorkflowNode):
    integration_type = "automation-deepimage"
    connection_evidence = ConnectionEvidence(noun="Deepimage account", operation="get_account", identity_operation="get_account", label_keys=("username", "email"))

    @classmethod
    def get_config_model(cls):
        return DeepimageConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Deepimage API key")
        config, key = self.config.config, self.config.credentials.api_key
        method, path, body = request_for(config)
        try:
            async with guarded_async_client(timeout=40, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"X-API-KEY": key, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
        except Exception:
            raise ValueError("Deepimage request could not be completed; inspect jobs before retrying a processing action") from None
        try:
            payload = response.json()
        except Exception:
            raise ValueError("Deepimage returned an unreadable response") from None
        if not isinstance(payload, dict):
            raise ValueError("Deepimage returned an unexpected response")
        if not 200 <= response.status_code < 300 or payload.get("code") or payload.get("status") in {"error", "failed"}:
            message = str(payload.get("message") or "Deepimage rejected the request").replace(key, "[redacted]")
            result = {"status": "error", "http_status": response.status_code, "message": message}
        elif config.operation == "get_account":
            if not any(isinstance(payload.get(k), str) and payload[k] for k in ("username", "email")):
                raise ValueError("Deepimage account identity is missing")
            # /me includes api_key, webhooks and billing details: never return them.
            result = {"status": "success", "data": {k: v for k, v in payload.items() if k in {"username", "email", "credits", "language"}}}
        elif config.operation == "delete_result":
            if not isinstance(payload.get("message"), str) or not payload["message"]:
                raise ValueError("Deepimage deletion acknowledgement is missing")
            result = {"status": "success", "message": payload["message"], "deletion_acknowledged": True}
        else:
            if not isinstance(payload.get("job"), str) or not payload["job"]:
                raise ValueError("Deepimage job hash is missing")
            state = payload.get("status")
            if state is not None and state not in {"received", "not_started", "in_progress", "complete"}:
                raise ValueError("Deepimage returned an unexpected job state")
            result = {"status": "success", "job": payload["job"], "job_status": state, "complete": state == "complete"}
            if isinstance(payload.get("result_url"), str):
                result["result_url"] = payload["result_url"]
        # Defense against a provider echoing the secret in a documented output field.
        def redact(value):
            if isinstance(value, str): return value.replace(key, "[redacted]")
            if isinstance(value, dict): return {k: redact(v) for k, v in value.items()}
            return value
        result = redact(result)
        await self.emit(result)
        return result
