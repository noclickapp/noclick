"""Apiframe v2: typed media submissions, job reads and LoRA management.

Contract: https://api.apiframe.ai/v2/openapi.json, version 2.0.0.
Submissions return job acceptance, not completed media. Poll get_job separately.
Curated generation models: Midjourney, Kling 2.1 and Suno; edits use Flux Fill,
Bria, Topaz and Wan 2.7. No request retries or automatic pagination.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.apiframe.ai"


class ApiframeAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Apiframe API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://console.apiframe.ai",
            "x-credential-instructions": "Create an API key in the Apiframe console and paste it here. NoClick sends it in X-API-Key to api.apiframe.ai. Media submissions consume your Apiframe credits; get_account verifies the caller and team.",
        })
    credential_type: Literal["apiframe_api_key"] = Field("apiframe_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ApiframeGetAccountConfig(_Input):
    """Get the authenticated caller."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})

class ApiframeListModelsConfig(_Input):
    """List the curated model catalog."""
    operation: Literal["list_models"] = Field("list_models", json_schema_extra={"ui:hidden": True})
    modality: Literal['image', 'video', 'music'] | None = Field(None)

class ApiframeListJobsConfig(_Input):
    """List jobs."""
    operation: Literal["list_jobs"] = Field("list_jobs", json_schema_extra={"ui:hidden": True})
    status: Literal['QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED', 'CANCELLED'] | None = Field(None)
    model: str | None = Field(None)
    limit: int = Field(20, ge=1, le=100)
    cursor: str | None = Field(None)
    scope: Literal['user', 'team'] = Field('user')
    search: UUID | None = Field(None)
    include_models: Literal['true', 'false'] = Field('false')

class ApiframeGetJobConfig(_Input):
    """Get a job."""
    operation: Literal["get_job"] = Field("get_job", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)

class ApiframeGenerateImageConfigMidjourneyParams(_Input):
    aspect_ratio: str | None = Field(None, pattern='^\\d+:\\d+$')

class ApiframeGenerateImageConfig(_Input):
    """Submit a Midjourney image generation job; poll get_job for results."""
    operation: Literal["generate_image"] = Field("generate_image", json_schema_extra={"ui:hidden": True})
    prompt: str = Field(..., min_length=1, max_length=2000)
    model: Literal['midjourney'] = Field('midjourney')
    webhookUrl: str | None = Field(None, pattern=r"^https?://[^\s]+$")
    webhookEvents: list[Literal['progress', 'completed', 'failed']] | None = Field(None, min_length=1)
    midjourneyParams: ApiframeGenerateImageConfigMidjourneyParams | None = Field(None)
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)

class ApiframeUpscaleImageConfigTopazUpscaleParams(_Input):
    image: str = Field(...)
    model_type: Literal['standard-v2', 'low-res-v2', 'cgi', 'high-fidelity-v2', 'text-refine', 'redefine'] | None = Field(None)
    upscale_factor: Literal[1, 2, 4, 6] | None = Field(None)
    face_enhance: StrictBool | None = Field(None)
    face_enhance_strength: float | None = Field(None, ge=0, le=1)
    face_enhance_creativity: float | None = Field(None, ge=0, le=1)
    output_format: Literal['jpg', 'png'] | None = Field(None)
    seed: int | None = Field(None)

class ApiframeUpscaleImageConfig(_Input):
    """Submit an image upscale job."""
    operation: Literal["upscale_image"] = Field("upscale_image", json_schema_extra={"ui:hidden": True})
    model: Literal['topaz-image-upscale'] = Field('topaz-image-upscale')
    webhookUrl: str | None = Field(None, pattern=r"^https?://[^\s]+$")
    webhookEvents: list[Literal['progress', 'completed', 'failed']] | None = Field(None, min_length=1)
    topazUpscaleParams: ApiframeUpscaleImageConfigTopazUpscaleParams = Field(...)
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)

class ApiframeMidjourneyActionConfig(_Input):
    """Run a follow-up action on a completed Midjourney image."""
    operation: Literal["midjourney_action"] = Field("midjourney_action", json_schema_extra={"ui:hidden": True})
    action: Literal['upsample'] = Field('upsample')
    index: Literal[1, 2, 3, 4] = Field(...)
    parentJobId: UUID = Field(...)
    webhookUrl: str | None = Field(None, pattern=r"^https?://[^\s]+$")
    webhookEvents: list[Literal['progress', 'completed', 'failed']] | None = Field(None, min_length=1)
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)

class ApiframeEditImageConfigFluxFillParams(_Input):
    image: str = Field(...)
    prompt: str = Field(..., min_length=1, max_length=2000)
    mode: Literal['inpaint', 'outpaint'] = Field(...)
    mask: str | None = Field(None)
    outpaint: Literal['Zoom out 1.5x', 'Zoom out 2x', 'Make square', 'Left outpaint', 'Right outpaint', 'Top outpaint', 'Bottom outpaint'] | None = Field(None)
    steps: int | None = Field(None, ge=1, le=50)
    guidance: float | None = Field(None, ge=2, le=5)
    safety_tolerance: int | None = Field(None, ge=1, le=6)
    output_format: Literal['jpg', 'png'] | None = Field(None)
    seed: int | None = Field(None)
    prompt_upsampling: StrictBool | None = Field(None)

    @model_validator(mode="after")
    def edit_input(self):
        if self.mode == "inpaint" and not self.mask or self.mode == "outpaint" and not self.outpaint:
            raise ValueError("Inpainting needs a mask; outpainting needs an outpaint preset")
        return self

class ApiframeEditImageConfig(_Input):
    """Submit an inpaint or outpaint job."""
    operation: Literal["edit_image"] = Field("edit_image", json_schema_extra={"ui:hidden": True})
    model: Literal['flux-fill-pro'] = Field('flux-fill-pro')
    webhookUrl: str | None = Field(None, pattern=r"^https?://[^\s]+$")
    webhookEvents: list[Literal['progress', 'completed', 'failed']] | None = Field(None, min_length=1)
    fluxFillParams: ApiframeEditImageConfigFluxFillParams = Field(...)
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)

class ApiframeRemoveImageBackgroundConfigBriaBgRemoveParams(_Input):
    image: str = Field(...)
    content_moderation: StrictBool | None = Field(None)

class ApiframeRemoveImageBackgroundConfig(_Input):
    """Submit a background-removal job."""
    operation: Literal["remove_image_background"] = Field("remove_image_background", json_schema_extra={"ui:hidden": True})
    model: Literal['bria-bg-remove'] = Field('bria-bg-remove')
    webhookUrl: str | None = Field(None, pattern=r"^https?://[^\s]+$")
    webhookEvents: list[Literal['progress', 'completed', 'failed']] | None = Field(None, min_length=1)
    briaBgRemoveParams: ApiframeRemoveImageBackgroundConfigBriaBgRemoveParams = Field(...)
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)

class ApiframeGenerateVideoConfigKlingParams(_Input):
    start_image: str | None = Field(None)
    end_image: str | None = Field(None)
    negative_prompt: str | None = Field(None, max_length=2500)
    mode: Literal['standard', 'pro'] | None = Field(None)
    duration: Literal[5, 10] | None = Field(None)

class ApiframeGenerateVideoConfig(_Input):
    """Submit a Kling 2.1 video generation job; poll get_job for results."""
    operation: Literal["generate_video"] = Field("generate_video", json_schema_extra={"ui:hidden": True})
    prompt: str = Field(..., min_length=1, max_length=4000)
    model: Literal['kling-2.1'] = Field('kling-2.1')
    webhookUrl: str | None = Field(None, pattern=r"^https?://[^\s]+$")
    webhookEvents: list[Literal['progress', 'completed', 'failed']] | None = Field(None, min_length=1)
    klingParams: ApiframeGenerateVideoConfigKlingParams | None = Field(None)
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)

class ApiframeUpscaleVideoConfigTopazVideoParams(_Input):
    video: str = Field(...)
    target_resolution: Literal['720p', '1080p', '4k'] = Field(...)
    target_fps: Literal[24, 30, 60] = Field(...)
    enhance_model: Literal['auto', 'theia-fine-tune-detail', 'theia-fine-tune-fidelity', 'apollo', 'rhea', 'iris'] | None = Field(None)
    subject_detection: Literal['all', 'foreground', 'background', 'none'] | None = Field(None)

class ApiframeUpscaleVideoConfig(_Input):
    """Submit a video upscale job."""
    operation: Literal["upscale_video"] = Field("upscale_video", json_schema_extra={"ui:hidden": True})
    model: Literal['topaz-video-upscale'] = Field('topaz-video-upscale')
    webhookUrl: str | None = Field(None, pattern=r"^https?://[^\s]+$")
    webhookEvents: list[Literal['progress', 'completed', 'failed']] | None = Field(None, min_length=1)
    topazVideoParams: ApiframeUpscaleVideoConfigTopazVideoParams = Field(...)
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)

class ApiframeEditVideoConfigWan27VideoeditParams(_Input):
    video: str = Field(...)
    reference_image: str | None = Field(None)
    negative_prompt: str | None = Field(None, max_length=2500)
    resolution: Literal['720p', '1080p'] | None = Field(None)
    aspect_ratio: Literal['auto', '16:9', '9:16', '1:1', '4:3', '3:4'] | None = Field(None)
    audio_setting: Literal['auto', 'origin'] | None = Field(None)
    duration: int | None = Field(None, ge=2, le=10)
    seed: int | None = Field(None)

class ApiframeEditVideoConfig(_Input):
    """Submit an instruction-based video edit job."""
    operation: Literal["edit_video"] = Field("edit_video", json_schema_extra={"ui:hidden": True})
    prompt: str = Field(..., min_length=1, max_length=5000)
    model: Literal['wan-2.7-videoedit'] = Field('wan-2.7-videoedit')
    webhookUrl: str | None = Field(None, pattern=r"^https?://[^\s]+$")
    webhookEvents: list[Literal['progress', 'completed', 'failed']] | None = Field(None, min_length=1)
    wan27VideoeditParams: ApiframeEditVideoConfigWan27VideoeditParams = Field(...)
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)

class ApiframeGenerateMusicConfigSunoParams(_Input):
    custom_mode: StrictBool = Field(False)
    instrumental: StrictBool = Field(False)
    model_version: Literal['V4', 'V4_5', 'V4_5ALL', 'V4_5PLUS', 'V5', 'V5_5'] = Field('V4_5PLUS')
    title: str | None = Field(None, max_length=80)
    style: str | None = Field(None, max_length=1000)
    negative_tags: str | None = Field(None, max_length=500)
    vocal_gender: Literal['m', 'f'] | None = Field(None)
    style_weight: float | None = Field(None, ge=0, le=1)
    weirdness_constraint: float | None = Field(None, ge=0, le=1)
    auto_lyrics: StrictBool | None = Field(None)

class ApiframeGenerateMusicConfig(_Input):
    """Submit a Suno music job; completed jobs can contain two songs."""
    operation: Literal["generate_music"] = Field("generate_music", json_schema_extra={"ui:hidden": True})
    prompt: str = Field(..., min_length=1, max_length=5000)
    model: Literal['suno'] = Field('suno')
    webhookUrl: str | None = Field(None, pattern=r"^https?://[^\s]+$")
    webhookEvents: list[Literal['progress', 'completed', 'failed']] | None = Field(None, min_length=1)
    sunoParams: ApiframeGenerateMusicConfigSunoParams | None = Field(None)
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)

class ApiframeGenerateLyricsConfig(_Input):
    """Write song lyrics with Udio."""
    operation: Literal["generate_lyrics"] = Field("generate_lyrics", json_schema_extra={"ui:hidden": True})
    prompt: str = Field(..., min_length=1, max_length=2000)
    duration: Literal[32, 65, 97, 130] | None = Field(None)
    lyrics: str | None = Field(None, max_length=5000)
    webhookUrl: str | None = Field(None, pattern=r"^https?://[^\s]+$")
    webhookEvents: list[Literal['progress', 'completed', 'failed']] | None = Field(None, min_length=1)
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)

class ApiframeListLorasConfig(_Input):
    """List the team's LoRAs."""
    operation: Literal["list_loras"] = Field("list_loras", json_schema_extra={"ui:hidden": True})
    cursor: UUID | None = Field(None)
    limit: int = Field(24, ge=1, le=100)
    includeArchived: Literal['true', 'false'] = Field('false')

class ApiframeGetLoraConfig(_Input):
    """Get a single LoRA."""
    operation: Literal["get_lora"] = Field("get_lora", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)

class ApiframeArchiveLoraConfig(_Input):
    """Archive a LoRA."""
    operation: Literal["archive_lora"] = Field("archive_lora", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)

ApiframeOperation = Annotated[Union[
    ApiframeGetAccountConfig,
    ApiframeListModelsConfig,
    ApiframeListJobsConfig,
    ApiframeGetJobConfig,
    ApiframeGenerateImageConfig,
    ApiframeUpscaleImageConfig,
    ApiframeMidjourneyActionConfig,
    ApiframeEditImageConfig,
    ApiframeRemoveImageBackgroundConfig,
    ApiframeGenerateVideoConfig,
    ApiframeUpscaleVideoConfig,
    ApiframeEditVideoConfig,
    ApiframeGenerateMusicConfig,
    ApiframeGenerateLyricsConfig,
    ApiframeListLorasConfig,
    ApiframeGetLoraConfig,
    ApiframeArchiveLoraConfig
], Field(discriminator="operation")]


class ApiframeNodeConfig(NodeConfig[ApiframeOperation, ApiframeAPIKeyCredential]):
    pass


ROUTES = {'get_account': ('GET', '/v2/me'),
 'list_models': ('GET', '/v2/models'),
 'list_jobs': ('GET', '/v2/jobs'),
 'get_job': ('GET', '/v2/jobs/{id}'),
 'generate_image': ('POST', '/v2/images/generate'),
 'upscale_image': ('POST', '/v2/images/upscale'),
 'midjourney_action': ('POST', '/v2/images/midjourney/action'),
 'edit_image': ('POST', '/v2/images/edit'),
 'remove_image_background': ('POST', '/v2/images/background-remove'),
 'generate_video': ('POST', '/v2/videos/generate'),
 'upscale_video': ('POST', '/v2/videos/upscale'),
 'edit_video': ('POST', '/v2/videos/edit'),
 'generate_music': ('POST', '/v2/music/generate'),
 'generate_lyrics': ('POST', '/v2/music/udio/lyrics'),
 'list_loras': ('GET', '/v2/loras'),
 'get_lora': ('GET', '/v2/loras/{id}'),
 'archive_lora': ('DELETE', '/v2/loras/{id}')}


class ApiframeNode(WorkflowNode):
    integration_type = "automation-apiframe"
    connection_evidence = ConnectionEvidence(noun="account", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return ApiframeNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Apiframe API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        key = values.pop("idempotency_key", None)
        if "{id}" in path:
            path = path.replace("{id}", str(values.pop("id")))
        headers = {"X-API-Key": self.config.credentials.api_key, "Accept": "application/json"}
        if key:
            headers["Idempotency-Key"] = key
        try:
            async with guarded_async_client(timeout=60.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, headers=headers,
                    **({"params": values} if method == "GET" else {"json": values} if method == "POST" else {}))
        except httpx.HTTPError:
            raise ValueError("Apiframe request could not be confirmed; inspect jobs before retrying a submission") from None
        if not 200 <= response.status_code < 300:
            try:
                detail = response.json().get("error", "Apiframe rejected the request")
            except (ValueError, AttributeError):
                detail = "Apiframe returned an unexpected response"
            return {"status": "error", "http_status": response.status_code,
                    "error": str(detail).replace(self.config.credentials.api_key, "[redacted]")}
        if method == "DELETE":
            if response.status_code != 204:
                raise ValueError("Apiframe did not confirm archival")
            return {"status": "success", "archived_id": str(config.id), "archived": True}
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Apiframe returned invalid JSON") from None
        if not isinstance(body, dict) or body.get("error") and config.operation not in {"get_job", "get_lora"}:
            raise ValueError("Apiframe returned an unexpected response")
        if method == "POST":
            if not isinstance(body.get("jobId"), str) or body.get("status") not in {"QUEUED", "PROCESSING", "COMPLETED", "FAILED"}:
                raise ValueError("Apiframe did not return a job acknowledgement")
            return {"status": "success", "accepted": True, "data": body}
        if config.operation == "get_account":
            user = body.get("user")
            if not isinstance(user, dict) or not user.get("id") or not user.get("email"):
                raise ValueError("Apiframe did not return the authenticated caller")
            return {"status": "success", "email": user["email"], "data": body}
        if config.operation in {"get_job", "get_lora"} and str(body.get("id")) != str(config.id):
            raise ValueError("Apiframe returned a different resource")
        if config.operation == "list_models" and not isinstance(body.get("models"), list):
            raise ValueError("Apiframe did not return the model catalog")
        if config.operation in {"get_job", "get_lora"}:
            allowed = {"QUEUED", "PROCESSING", "COMPLETED", "FAILED", "CANCELLED"} if config.operation == "get_job" else {"PENDING", "UPLOADING", "TRAINING", "READY", "FAILED", "ARCHIVED"}
            if body.get("status") not in allowed:
                raise ValueError("Apiframe returned an invalid resource status")
        if config.operation in {"list_jobs", "list_loras"}:
            rows = body.get("jobs" if config.operation == "list_jobs" else "items")
            cursor = body.get("nextCursor")
            if not isinstance(rows, list) or len(rows) > config.limit or "nextCursor" not in body or cursor is not None and not isinstance(cursor, str):
                raise ValueError("Apiframe did not return a valid page")
            if config.operation == "list_jobs" and type(body.get("hasMore")) is not bool:
                raise ValueError("Apiframe omitted job pagination state")
        return {"status": "success", "data": body}
