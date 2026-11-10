"""DreamStudio/Stability AI v1 image generation and account reads.

Contract: Stability-AI/rest-api-support generated/spec/merged.json, version v1.
The documented modes are separate actions, each making exactly one API call.
Images are supplied as base64, decoded locally and uploaded as multipart bytes;
no arbitrary URLs are fetched. Generation is billable and never retried here.
"""
from __future__ import annotations

import base64
import binascii
import math
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE = "https://api.stability.ai"
CREDENTIAL = "dreamstudio_api_key"


class DreamstudioAPIKey(BaseModel):
    model_config = ConfigDict(title="DreamStudio API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://platform.stability.ai/account/keys",
            "x-credential-instructions": "Paste your Stability AI API key, without the Bearer prefix. Image generation uses your account credits. NoClick verifies the key by reading your account."})
    credential_type: Literal["dreamstudio_api_key"] = Field(CREDENTIAL, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() for c in value) or len(value) > 4096:
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetAccount(_Config):
    """Read your account identity and organization memberships."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class _Organization(_Config):
    organization: str | None = Field(None, max_length=128, pattern=r"^[A-Za-z0-9_-]+$",
        description="Optional organization ID; otherwise uses your default organization.")


class GetBalance(_Organization):
    """Read the credit balance for your account or organization."""
    operation: Literal["get_balance"] = Field("get_balance", json_schema_extra={"ui:hidden": True})


class ListEngines(_Organization):
    """List engines available to your account or organization."""
    operation: Literal["list_engines"] = Field("list_engines", json_schema_extra={"ui:hidden": True})


class _Engine(_Organization):
    engine_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$",
        description="Engine ID from List Engines; choose an engine supporting this action.")


class TextPrompt(_Config):
    text: str = Field(..., min_length=1, max_length=2000)
    weight: float | None = Field(None, allow_inf_nan=False, description="Negative weights discourage the prompt.")


class _Generation(_Engine):
    text_prompts: list[TextPrompt] = Field(..., min_length=1, title="Text Prompts")
    cfg_scale: float = Field(7, ge=0, le=35, allow_inf_nan=False)
    clip_guidance_preset: Literal["FAST_BLUE", "FAST_GREEN", "NONE", "SIMPLE", "SLOW", "SLOWER", "SLOWEST"] = "NONE"
    sampler: Literal["DDIM", "DDPM", "K_DPMPP_2M", "K_DPMPP_2S_ANCESTRAL", "K_DPM_2", "K_DPM_2_ANCESTRAL", "K_EULER", "K_EULER_ANCESTRAL", "K_HEUN", "K_LMS"] | None = None
    samples: int = Field(1, ge=1, le=10)
    seed: int = Field(0, ge=0, le=4294967295)
    steps: int = Field(50, ge=10, le=150)


class TextToImage(_Generation):
    """Generate images from weighted text prompts (uses credits)."""
    operation: Literal["text_to_image"] = Field("text_to_image", json_schema_extra={"ui:hidden": True})
    width: int = Field(512, ge=128, multiple_of=64)
    height: int = Field(512, ge=128, multiple_of=64)

    @model_validator(mode="after")
    def dimensions(self):
        minimum = 589824 if "768" in self.engine_id else 262144
        if not minimum <= self.width * self.height <= 1048576:
            raise ValueError("Image area must fit the engine's documented pixel limits")
        return self


def _image(value):
    if not isinstance(value, str) or not value or len(value) > 40_000_000:
        raise ValueError("Supply image bytes encoded as base64, without a data URL prefix")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Supply valid base64 image bytes") from None
    if not decoded.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Supply a PNG image encoded as base64")
    return value


class _InitImage(_Generation):
    init_image: str = Field(..., repr=False, description="PNG image bytes encoded as base64; dimensions must match the engine.", json_schema_extra={"ui:widget": "textarea", "contentEncoding": "base64", "contentMediaType": "image/png"})
    _png = field_validator("init_image", mode="before")(_image)


class ImageStrength(_InitImage):
    """Transform an image using image strength (uses credits)."""
    operation: Literal["image_to_image_strength"] = Field("image_to_image_strength", json_schema_extra={"ui:hidden": True})
    image_strength: float = Field(0.35, ge=0, le=1, allow_inf_nan=False)


class ImageSchedule(_InitImage):
    """Transform an image using diffusion step scheduling (uses credits)."""
    operation: Literal["image_to_image_schedule"] = Field("image_to_image_schedule", json_schema_extra={"ui:hidden": True})
    step_schedule_start: float = Field(0.65, ge=0, le=1, allow_inf_nan=False)
    step_schedule_end: float | None = Field(None, ge=0, le=1, allow_inf_nan=False)


class UpscaleImage(_Engine):
    """Upscale a PNG, optionally choosing one target dimension (uses credits)."""
    operation: Literal["upscale_image"] = Field("upscale_image", json_schema_extra={"ui:hidden": True})
    image: str = Field(..., repr=False, description="PNG bytes encoded as base64.", json_schema_extra={"contentEncoding": "base64", "contentMediaType": "image/png"})
    width: int | None = Field(None, ge=512)
    height: int | None = Field(None, ge=512)
    _png = field_validator("image", mode="before")(_image)

    @model_validator(mode="after")
    def one_dimension(self):
        if self.width is not None and self.height is not None:
            raise ValueError("Specify only width or height, or neither for 2x upscaling")
        return self


class MaskAlpha(_InitImage):
    """Inpaint transparent pixels from the source PNG alpha channel (uses credits)."""
    operation: Literal["mask_alpha"] = Field("mask_alpha", json_schema_extra={"ui:hidden": True})


class _MaskImage(_InitImage):
    mask_image: str = Field(..., repr=False, description="Grayscale PNG mask encoded as base64, with the same dimensions as the source.", json_schema_extra={"contentEncoding": "base64", "contentMediaType": "image/png"})
    _mask = field_validator("mask_image", mode="before")(_image)


class MaskWhite(_MaskImage):
    """Inpaint white mask pixels while preserving black pixels (uses credits)."""
    operation: Literal["mask_white"] = Field("mask_white", json_schema_extra={"ui:hidden": True})


class MaskBlack(_MaskImage):
    """Inpaint black mask pixels while preserving white pixels (uses credits)."""
    operation: Literal["mask_black"] = Field("mask_black", json_schema_extra={"ui:hidden": True})


DreamstudioConfig = Annotated[Union[GetAccount, GetBalance, ListEngines, TextToImage,
    ImageStrength, ImageSchedule, UpscaleImage, MaskAlpha, MaskWhite, MaskBlack], Field(discriminator="operation")]


class DreamstudioNodeConfig(NodeConfig[DreamstudioConfig, DreamstudioAPIKey]):
    pass


class DreamstudioNode(WorkflowNode):
    integration_type = "automation-dreamstudio"
    connection_evidence = ConnectionEvidence(noun="account", identity_operation="get_account", label_keys=("email", "id"))

    @classmethod
    def get_config_model(cls):
        return DreamstudioNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a DreamStudio API key")
        op = self.config.config
        key = self.config.credentials.api_key
        action = op.operation
        headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
        if getattr(op, "organization", None):
            headers["Organization"] = op.organization
        kwargs = {}
        if action in {"get_account", "get_balance", "list_engines"}:
            method = "GET"
            path = {"get_account": "/v1/user/account", "get_balance": "/v1/user/balance", "list_engines": "/v1/engines/list"}[action]
        else:
            method = "POST"
            suffix = "text-to-image" if action == "text_to_image" else "image-to-image"
            if action == "upscale_image":
                suffix += "/upscale"
            elif action.startswith("mask_"):
                suffix += "/masking"
            path = f"/v1/generation/{op.engine_id}/{suffix}"
            body = op.model_dump(exclude={"operation", "engine_id", "organization"}, exclude_none=True)
            if action == "text_to_image":
                kwargs["json"] = body
            else:
                files = {}
                for field in ("init_image", "image", "mask_image"):
                    if field in body:
                        files[field] = (field + ".png", base64.b64decode(body.pop(field), validate=True), "image/png")
                for index, prompt in enumerate(body.pop("text_prompts", [])):
                    for field, value in prompt.items():
                        body[f"text_prompts[{index}][{field}]"] = value
                if action == "image_to_image_strength":
                    body["init_image_mode"] = "IMAGE_STRENGTH"
                elif action == "image_to_image_schedule":
                    body["init_image_mode"] = "STEP_SCHEDULE"
                elif action.startswith("mask_"):
                    body["mask_source"] = {"mask_alpha": "INIT_IMAGE_ALPHA", "mask_white": "MASK_IMAGE_WHITE", "mask_black": "MASK_IMAGE_BLACK"}[action]
                kwargs = {"data": {k: str(v) for k, v in body.items()}, "files": files}
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, headers=headers, **kwargs)
        except httpx.HTTPError:
            result = {"status": "error", "success": False, "message": "DreamStudio request did not complete; inspect your account before retrying a generation."}
        else:
            if response.status_code != 200:
                try:
                    error = response.json()
                    message = error.get("message") if isinstance(error, dict) else None
                except ValueError:
                    message = None
                result = {"status": "error", "success": False, "http_status": response.status_code,
                    "message": (message if isinstance(message, str) else f"DreamStudio returned HTTP {response.status_code}").replace(key, "[redacted]")[:2000]}
            else:
                try:
                    payload = response.json()
                    result = self._result(action, payload)
                except (ValueError, TypeError, KeyError):
                    result = {"status": "error", "success": False, "message": "DreamStudio returned an unexpected response; inspect your account before retrying a generation."}
        await self.emit(result)
        return result

    @staticmethod
    def _result(action, payload):
        if action == "get_account":
            if not isinstance(payload, dict) or not isinstance(payload.get("id"), str) or not isinstance(payload.get("email"), str) or not isinstance(payload.get("organizations"), list):
                raise ValueError("Invalid account")
            return {"status": "success", "success": True, "data": payload}
        if action == "get_balance":
            credits = payload.get("credits") if isinstance(payload, dict) else None
            if type(credits) not in {int, float} or not math.isfinite(credits):
                raise ValueError("Invalid balance")
            return {"status": "success", "success": True, "credits": credits}
        if action == "list_engines":
            if not isinstance(payload, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in payload):
                raise ValueError("Invalid engines")
            return {"status": "success", "success": True, "engines": payload}
        # Published schemas say array; the same provider's Python/JS examples
        # explicitly read data["artifacts"]. Preserve support for both contracts.
        images = payload.get("artifacts") if isinstance(payload, dict) else payload
        if not isinstance(images, list) or not images:
            raise ValueError("Invalid image response")
        for image in images:
            if not isinstance(image, dict) or not isinstance(image.get("base64"), str) or image.get("finishReason") not in {"SUCCESS", "ERROR", "CONTENT_FILTERED"} or type(image.get("seed")) not in {int, float}:
                raise ValueError("Invalid image")
        complete = all(image["finishReason"] == "SUCCESS" for image in images)
        return {"status": "success", "success": True, "generation_success": complete,
            "artifacts": images, "message": "Generation completed" if complete else "Some images were filtered or failed; inspect finishReason before using them."}
