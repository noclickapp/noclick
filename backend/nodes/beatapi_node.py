"""BeatAPI media workflows using a manually supplied bearer API key.

Each action performs one documented request. Task creation returns an accepted
task, not a completed generation; use get_task at the provider's poll interval.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.beatapi.io"


def public_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Use a public HTTPS media or callback URL")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith((".localhost", ".local")) or "." not in host:
        raise ValueError("Use a public HTTPS URL")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Private media and callback addresses are unsupported")
    return value


MediaURL = Annotated[str, Field(min_length=1, max_length=8192, pattern=r"^https://")]
ResourceID = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]


class BeatapiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Beatapi API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://beatapi.io/dashboard/apikeys",
        "x-credential-instructions": "Create an API key in BeatAPI Dashboard → API Keys and paste it here without the Bearer prefix. Generation and editing spend your BeatAPI USD balance. NoClick checks account usage when you connect.",
    })
    credential_type: Literal["beatapi_api_key"] = Field("beatapi_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value or len(value) > 4096 or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a Bearer prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def urls(cls, value, info):
        if info.field_name in {"images", "reference_images", "reference_videos", "reference_audios"} and value is not None:
            return [public_url(item) for item in value]
        if info.field_name in {"audio_url", "video_url", "lip_ref_url", "srt_url", "url"} and value is not None:
            return public_url(value)
        return value


class ListWorkflows(Input):
    operation: Literal["list_workflows"] = Field("list_workflows", title="List Workflows", json_schema_extra={"ui:hidden": True})


class ListModels(Input):
    operation: Literal["list_models"] = Field("list_models", title="List Models", json_schema_extra={"ui:hidden": True})
    media_type: Literal["image", "video"] | None = None


class ListEffects(Input):
    operation: Literal["list_effects"] = Field("list_effects", title="List Effects", json_schema_extra={"ui:hidden": True})
    output_type: Literal["image", "video"] | None = None
    category: str | None = None


class GetEffect(Input):
    operation: Literal["get_effect"] = Field("get_effect", title="Get Effect", json_schema_extra={"ui:hidden": True})
    effect_id: ResourceID


class GetUsage(Input):
    operation: Literal["get_usage"] = Field("get_usage", title="Get Usage", json_schema_extra={"ui:hidden": True})
    period: Literal["24h", "7d", "30d", "all"] = "all"


class GetTask(Input):
    operation: Literal["get_task"] = Field("get_task", title="Get Task", json_schema_extra={"ui:hidden": True})
    task_id: ResourceID


class TaskWrite(Input):
    idempotency_key: str | None = Field(None, min_length=1, max_length=255, description="Optional provider retry key. Reuse only with the identical path and body; NoClick does not automatically retry writes.")

    @field_validator("idempotency_key")
    @classmethod
    def header(cls, value):
        if value is not None and (not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value)):
            raise ValueError("Use a printable ASCII idempotency key without spaces")
        return value


class CreateImageTask(TaskWrite):
    """Generate or edit an image with Qwen Image 2.1."""
    operation: Literal["create_image_task"] = Field("create_image_task", title="Create Image Task", json_schema_extra={"ui:hidden": True})
    model: Literal["qwen-image-2.1"] = "qwen-image-2.1"
    prompt: str = Field(..., min_length=1, max_length=5000)
    images: list[MediaURL] | None = Field(None, min_length=1, max_length=10)
    aspect_ratio: Literal["auto", "1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16", "21:9", "9:21"] = "auto"
    background: Literal["opaque", "transparent"] = "opaque"
    enhance_prompt: bool | None = None
    output_format: Literal["png", "webp", "jpeg"] = "png"
    resolution: Literal["1K", "2K"] = "1K"
    seed: int | None = Field(None, ge=0, le=2147483647)

    @model_validator(mode="after")
    def transparent(self):
        if self.background == "transparent" and self.output_format == "jpeg":
            raise ValueError("Transparent images require PNG or WebP")
        return self


class CreateVideoTask(TaskWrite):
    """Generate video with MiniMax H3; references and frames are distinct modes."""
    operation: Literal["create_video_task"] = Field("create_video_task", title="Create Video Task", json_schema_extra={"ui:hidden": True})
    model: Literal["minimax-h3"] = "minimax-h3"
    prompt: str = Field(..., min_length=1, max_length=5000)
    images: list[MediaURL] | None = Field(None, min_length=1, max_length=2)
    reference_images: list[MediaURL] | None = Field(None, min_length=1, max_length=9)
    reference_videos: list[MediaURL] | None = Field(None, min_length=1, max_length=3)
    reference_audios: list[MediaURL] | None = Field(None, min_length=1, max_length=3)
    duration: int = Field(5, ge=4, le=30)
    aspect_ratio: Literal["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"] | None = None
    resolution: Literal["480p", "768P", "1080p", "2K"] = "768P"

    @model_validator(mode="after")
    def modes(self):
        references = self.reference_images or self.reference_videos or self.reference_audios
        if self.images and references:
            raise ValueError("Frame images cannot be combined with reference inputs")
        if self.reference_audios and not (self.reference_images or self.reference_videos):
            raise ValueError("Audio references require an image or video reference")
        if self.resolution == "2K" and self.duration > 15:
            raise ValueError("2K video supports at most 15 seconds")
        if self.images and self.aspect_ratio not in {None, "adaptive"}:
            raise ValueError("Frame mode requires adaptive aspect ratio")
        if not self.images and not references and self.aspect_ratio == "adaptive":
            raise ValueError("Text mode does not accept adaptive aspect ratio")
        return self


class EffectOptions(Input):
    aspect_ratio: str | None = None
    resolution: str | None = None
    duration: int | None = None
    bgm: bool | None = None
    seed: int | None = None


class CreateEffectTask(TaskWrite):
    operation: Literal["create_effect_task"] = Field("create_effect_task", title="Create Effect Task", json_schema_extra={"ui:hidden": True})
    effect_id: ResourceID
    effect_version: int | None = Field(None, ge=1)
    images: list[MediaURL] = Field(..., min_length=1, max_length=7)
    options: EffectOptions | None = Field(None, description="Use only controls advertised by get_effect for this version.")


class CreateVideoAnalysisTask(Input):
    operation: Literal["create_video_analysis_task"] = Field("create_video_analysis_task", title="Create Video Analysis Task", json_schema_extra={"ui:hidden": True})
    video_url: MediaURL = Field(..., description="BeatAPI-hosted MP4 or MOV from this account's file upload; maximum 600 seconds.")
    prompt: str = Field(..., min_length=1, max_length=12000)
    analysis_depth: Literal["standard", "deep"] = "standard"
    max_output_tokens: int = Field(2048, ge=256, le=8192)


class CreateMusicVideoTask(TaskWrite):
    """Create a Standard music video. Poll the returned task before editing."""
    operation: Literal["create_music_video_task"] = Field("create_music_video_task", title="Create Music Video Task", json_schema_extra={"ui:hidden": True})
    mv_tier: Literal["standard"] = "standard"
    images: list[MediaURL] = Field(..., min_length=1, max_length=7)
    audio_url: MediaURL
    prompt: str | None = Field(None, max_length=3000)
    language: Literal["en", "zh"] | None = None
    quality: Literal["standard", "high"] = "standard"
    style: str | None = Field(None, max_length=200)
    aspect_ratio: Literal["1:1", "16:9", "9:16", "4:3", "3:4"] | None = None
    resolution: Literal["540p", "720p", "1080p"] = "720p"
    lip_sync: bool = False
    lip_ref_url: MediaURL | None = None
    add_subtitle: bool = False
    subtitle_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    srt_url: MediaURL | None = None
    duration: int | None = Field(None, ge=10, le=180)
    compose_mode: Literal["auto", "manual"] = "auto"

    @model_validator(mode="after")
    def quality_rules(self):
        if self.lip_sync and not self.lip_ref_url:
            raise ValueError("Lip sync requires a face image URL")
        if self.resolution == "540p" and (self.quality == "high" or self.lip_sync):
            raise ValueError("540p does not support high quality or lip sync")
        return self


class EditMusicVideoShot(TaskWrite):
    operation: Literal["edit_music_video_shot"] = Field("edit_music_video_shot", title="Edit Music Video Shot", json_schema_extra={"ui:hidden": True})
    task_id: ResourceID
    shot_id: ResourceID
    prompt: str = Field(..., max_length=3000)
    images: list[MediaURL] | None = Field(None, max_length=6, description="Premium tasks only; omit for Standard tasks.")


class GetMusicVideoShotMedia(Input):
    operation: Literal["get_music_video_shot_media"] = Field("get_music_video_shot_media", title="Get Music Video Shot Media", json_schema_extra={"ui:hidden": True})
    task_id: ResourceID
    shot_id: ResourceID


class ComposeMusicVideoTask(TaskWrite):
    operation: Literal["compose_music_video_task"] = Field("compose_music_video_task", title="Compose Music Video Task", json_schema_extra={"ui:hidden": True})
    task_id: ResourceID
    shot_ids: list[ResourceID] = Field(..., min_length=1)


class CreateEcommerceVideoTask(TaskWrite):
    operation: Literal["create_ecommerce_video_task"] = Field("create_ecommerce_video_task", title="Create Ecommerce Video Task", json_schema_extra={"ui:hidden": True})
    images: list[MediaURL] = Field(..., min_length=1, max_length=7)
    duration: int = Field(..., ge=10, le=60)
    prompt: str | None = Field(None, max_length=2000)
    aspect_ratio: Literal["16:9", "9:16", "1:1"] | None = None
    language: Literal["en", "zh"] | None = None


class ListWebhooks(Input):
    operation: Literal["list_webhooks"] = Field("list_webhooks", title="List Webhooks", json_schema_extra={"ui:hidden": True})


class CreateWebhook(Input):
    operation: Literal["create_webhook"] = Field("create_webhook", title="Create Webhook", json_schema_extra={"ui:hidden": True})
    url: MediaURL
    description: str | None = None
    events: list[Literal["task.succeeded", "task.failed"]] | None = None


class GetWebhook(Input):
    operation: Literal["get_webhook"] = Field("get_webhook", title="Get Webhook", json_schema_extra={"ui:hidden": True})
    webhook_id: ResourceID


class UpdateWebhook(Input):
    operation: Literal["update_webhook"] = Field("update_webhook", title="Update Webhook", json_schema_extra={"ui:hidden": True})
    webhook_id: ResourceID
    url: MediaURL | None = None
    description: str | None = None
    events: list[Literal["task.succeeded", "task.failed"]] | None = None
    status: Literal["active", "disabled"] | None = None


class DeleteWebhook(Input):
    operation: Literal["delete_webhook"] = Field("delete_webhook", title="Delete Webhook", json_schema_extra={"ui:hidden": True})
    webhook_id: ResourceID


Operation = Annotated[Union[ListWorkflows, ListModels, ListEffects, GetEffect, GetUsage, GetTask,
    CreateImageTask, CreateVideoTask, CreateEffectTask, CreateVideoAnalysisTask, CreateMusicVideoTask,
    EditMusicVideoShot, GetMusicVideoShotMedia, ComposeMusicVideoTask, CreateEcommerceVideoTask,
    ListWebhooks, CreateWebhook, GetWebhook, UpdateWebhook, DeleteWebhook], Field(discriminator="operation")]


class BeatapiConfig(NodeConfig[Operation, BeatapiAPIKeyCredential]):
    pass


# Fixed routes keep every action tied to exactly one published API operation.
ROUTES = {
    "list_workflows": ("GET", "/v1/workflows", 200),
    "list_models": ("GET", "/v1/media/models", 200),
    "list_effects": ("GET", "/v1/effects", 200),
    "get_effect": ("GET", "/v1/effects/{effect_id}", 200),
    "get_usage": ("GET", "/v1/usage", 200),
    "get_task": ("GET", "/v1/tasks/{task_id}", 200),
    "create_image_task": ("POST", "/v1/images/tasks", 201),
    "create_video_task": ("POST", "/v1/videos/tasks", 201),
    "create_effect_task": ("POST", "/v1/effects/tasks", 201),
    "create_video_analysis_task": ("POST", "/v1/video-analysis/tasks", 201),
    "create_music_video_task": ("POST", "/v1/music-video/tasks", 201),
    "edit_music_video_shot": ("POST", "/v1/music-video/tasks/{task_id}/shots/{shot_id}/edit", 202),
    "get_music_video_shot_media": ("POST", "/v1/music-video/tasks/{task_id}/shots/{shot_id}/media", 200),
    "compose_music_video_task": ("POST", "/v1/music-video/tasks/{task_id}/compose", 202),
    "create_ecommerce_video_task": ("POST", "/v1/ecommerce-video/tasks", 201),
    "list_webhooks": ("GET", "/v1/webhooks", 200),
    "create_webhook": ("POST", "/v1/webhooks", 201),
    "get_webhook": ("GET", "/v1/webhooks/{webhook_id}", 200),
    "update_webhook": ("PATCH", "/v1/webhooks/{webhook_id}", 200),
    "delete_webhook": ("DELETE", "/v1/webhooks/{webhook_id}", 200),
}


class BeatapiNode(WorkflowNode):
    integration_type = "automation-beatapi"
    connection_evidence = ConnectionEvidence(noun="BeatAPI account usage", operation="get_usage")

    @classmethod
    def get_config_model(cls):
        return BeatapiConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a BeatAPI API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, route, expected = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation", "idempotency_key"})
        for field in re.findall(r"{(\w+)}", route):
            route = route.replace("{" + field + "}", quote(values.pop(field), safe=""))
        headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
        retry_key = getattr(op, "idempotency_key", None)
        if retry_key:
            headers["Idempotency-Key"] = retry_key
        kwargs = {"params": values} if method == "GET" else {"json": values} if values or method == "PATCH" else {}
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route, headers=headers, **kwargs)
        except (httpx.HTTPError, OSError):
            raise ValueError("BeatAPI request did not complete; inspect task state before retrying a write") from None
        if response.status_code != expected:
            message = "BeatAPI request failed"
            try:
                error = response.json().get("error", {})
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"][:2000].replace(key, "[redacted]")
            except (ValueError, AttributeError):
                pass
            raise ValueError(f"BeatAPI HTTP {response.status_code}: {message}")
        if len(response.content) > 8_000_000 or response.headers.get("content-type", "").split(";")[0].lower() != "application/json":
            raise ValueError("BeatAPI returned an unsupported response")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("BeatAPI returned invalid JSON") from None
        if not isinstance(payload, dict) or payload.get("error") or not isinstance(payload.get("data"), dict):
            raise ValueError("BeatAPI returned an invalid data envelope")
        result = {"status": "success", "data": payload["data"], "http_status": response.status_code}
        await self.emit(result)
        return result
