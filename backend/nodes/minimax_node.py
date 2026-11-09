"""MiniMax API automation, pinned to the provider's published OpenAPI contracts.

Each operation makes one provider request. Async creation returns a task ID;
query operations are explicit workflow steps. Media is requested as URLs.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.binary_output import BinaryOutput
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.minimax.io"


class MinimaxAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="MiniMax API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "api_key",
            "x-credential-url": "https://platform.minimax.io/user-center/basic-information/interface-key",
            "x-credential-instructions": "Create an API key in MiniMax Account Management → API Keys and paste it here. NoClick uses it to call api.minimax.io. Connecting reads your file list; generation operations use your MiniMax balance.",
        },
    )
    credential_type: Literal["minimax_api_key"] = Field("minimax_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix or spaces")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class MinimaxListModelsConfig(_Input):
    """List text models available through the OpenAI-compatible endpoint."""
    operation: Literal["list_models"] = Field("list_models", json_schema_extra={"ui:hidden": True})


class MinimaxGetModelConfig(_Input):
    """Retrieve one text model's metadata."""
    operation: Literal["get_model"] = Field("get_model", json_schema_extra={"ui:hidden": True})
    model_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class MinimaxListFilesConfig(_Input):
    """List files belonging to the connected account, optionally by purpose."""
    operation: Literal["list_files"] = Field("list_files", json_schema_extra={"ui:hidden": True})
    purpose: Literal["voice_clone", "prompt_audio", "t2a_async_input", "video_generation_input"] | None = None


class MinimaxGetFileConfig(_Input):
    """Retrieve a file's metadata and download URL."""
    operation: Literal["get_file"] = Field("get_file", json_schema_extra={"ui:hidden": True})
    file_id: int = Field(..., gt=0)


class MinimaxDeleteFileConfig(_Input):
    """Delete a selected file from the MiniMax account."""
    operation: Literal["delete_file"] = Field("delete_file", json_schema_extra={"ui:hidden": True})
    file_id: int = Field(..., gt=0)
    purpose: Literal["voice_clone", "prompt_audio", "t2a_async", "t2a_async_input", "video_generation"]


class MinimaxChatConfig(_Input):
    """Generate a text reply using MiniMax's OpenAI-compatible API."""
    operation: Literal["generate_text"] = Field("generate_text", json_schema_extra={"ui:hidden": True})
    model: Literal["MiniMax-M3.1-Flash", "MiniMax-M3"] = "MiniMax-M3.1-Flash"
    prompt: str = Field(..., min_length=1, json_schema_extra={"ui:widget": "textarea"})
    system_prompt: str | None = None
    max_completion_tokens: int | None = Field(None, ge=1, le=524288)
    reasoning_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None


class MinimaxImageConfig(_Input):
    """Generate images and return their temporary download URLs."""
    operation: Literal["generate_image"] = Field("generate_image", json_schema_extra={"ui:hidden": True})
    prompt: str = Field(..., min_length=1, max_length=1500, json_schema_extra={"ui:widget": "textarea"})
    model: Literal["image-01"] = "image-01"
    aspect_ratio: Literal["1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "21:9"] = "1:1"
    n: int = Field(1, ge=1, le=9)
    seed: int | None = None
    prompt_optimizer: bool = False


class MinimaxMusicConfig(_Input):
    """Generate music as a download URL, with lyrics or an instrumental prompt."""
    operation: Literal["generate_music"] = Field("generate_music", json_schema_extra={"ui:hidden": True})
    model: Literal["music-3.0", "music-2.6", "music-3.0-free", "music-2.6-free"] = "music-3.0"
    prompt: str = Field(..., min_length=1, max_length=2000)
    lyrics: str | None = Field(None, max_length=3500)
    is_instrumental: bool = False
    lyrics_optimizer: bool = True


class MinimaxLyricsConfig(_Input):
    """Write a full song or edit existing lyrics."""
    operation: Literal["generate_lyrics"] = Field("generate_lyrics", json_schema_extra={"ui:hidden": True})
    mode: Literal["write_full_song", "edit"] = "write_full_song"
    prompt: str = Field(..., min_length=1)
    lyrics: str | None = None
    title: str | None = None

    @model_validator(mode="after")
    def edit_requires_lyrics(self):
        if self.mode == "edit" and not self.lyrics:
            raise ValueError("Provide the lyrics to edit")
        return self


SpeechModel = Literal["speech-2.8-hd", "speech-2.8-turbo", "speech-2.6-hd", "speech-2.6-turbo", "speech-02-hd", "speech-02-turbo", "speech-01-hd", "speech-01-turbo"]


class _Speech(_Input):
    model: SpeechModel = "speech-2.8-hd"
    text: str = Field(..., min_length=1, max_length=9999, json_schema_extra={"ui:widget": "textarea"})
    voice_id: str = Field(..., min_length=1, description="A system, cloned or designed voice ID from List Voices.")
    speed: float = Field(1.0, ge=0.5, le=2)
    vol: float = Field(1.0, gt=0, le=10)
    pitch: int = Field(0, ge=-12, le=12)


class MinimaxSpeechConfig(_Speech):
    """Synthesize speech synchronously and return an audio URL."""
    operation: Literal["generate_speech"] = Field("generate_speech", json_schema_extra={"ui:hidden": True})


class MinimaxAsyncSpeechConfig(_Speech):
    """Submit a speech synthesis task; query it in a later workflow step."""
    operation: Literal["create_speech_task"] = Field("create_speech_task", json_schema_extra={"ui:hidden": True})
    text: str = Field(..., min_length=1, max_length=1000000, json_schema_extra={"ui:widget": "textarea"})


class MinimaxGetSpeechTaskConfig(_Input):
    """Query an asynchronous speech task's status and file ID."""
    operation: Literal["get_speech_task"] = Field("get_speech_task", json_schema_extra={"ui:hidden": True})
    task_id: int = Field(..., gt=0)


class MinimaxListVoicesConfig(_Input):
    """List system, cloned or designed voices."""
    operation: Literal["list_voices"] = Field("list_voices", json_schema_extra={"ui:hidden": True})
    voice_type: Literal["system", "voice_cloning", "voice_generation", "all"] = "all"


class MinimaxDeleteVoiceConfig(_Input):
    """Delete a selected cloned or designed voice."""
    operation: Literal["delete_voice"] = Field("delete_voice", json_schema_extra={"ui:hidden": True})
    voice_type: Literal["voice_cloning", "voice_generation"]
    voice_id: str = Field(..., min_length=1)


class MinimaxDesignVoiceConfig(_Input):
    """Design a voice from a description and generate a preview."""
    operation: Literal["design_voice"] = Field("design_voice", json_schema_extra={"ui:hidden": True})
    prompt: str = Field(..., min_length=1)
    preview_text: str = Field(..., min_length=1)
    voice_id: str | None = None


class MinimaxCloneVoiceConfig(_Input):
    """Clone a voice from a file already uploaded to MiniMax."""
    operation: Literal["clone_voice"] = Field("clone_voice", json_schema_extra={"ui:hidden": True})
    file_id: int = Field(..., gt=0)
    voice_id: str = Field(..., min_length=8, max_length=256, pattern=r"^[A-Za-z][A-Za-z0-9_-]*[A-Za-z0-9]$")
    need_noise_reduction: bool = False
    need_volume_normalization: bool = False


class MinimaxCreateVideoConfig(_Input):
    """Create an H3 video task from text and an optional first-frame image."""
    operation: Literal["create_video_task"] = Field("create_video_task", json_schema_extra={"ui:hidden": True})
    model: Literal["MiniMax-H3", "MiniMax-H3-Highspeed", "MiniMax-H3-Lite", "MiniMax-H3-Max"] = "MiniMax-H3"
    prompt: str = Field(..., min_length=1, max_length=7000, json_schema_extra={"ui:widget": "textarea"})
    first_frame_url: str | None = Field(None, description="Public image URL or mm_file:// file reference. MiniMax fetches the media.")
    resolution: Literal["480P", "768P", "2K"] = "768P"
    duration: int = Field(6, ge=4, le=15)
    ratio: Literal["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"] = "16:9"

    @model_validator(mode="after")
    def supported_combination(self):
        if self.model == "MiniMax-H3" and self.resolution == "480P":
            raise ValueError("MiniMax-H3 requires 768P or 2K")
        if self.model != "MiniMax-H3" and self.resolution == "2K":
            raise ValueError("2K requires MiniMax-H3")
        if self.model == "MiniMax-H3-Max" and self.duration < 5:
            raise ValueError("MiniMax-H3-Max requires at least 5 seconds")
        return self


class _VideoTask(_Input):
    task_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")


class MinimaxGetVideoConfig(_VideoTask):
    """Query an H3 video task and retrieve its result URL when complete."""
    operation: Literal["get_video_task"] = Field("get_video_task", json_schema_extra={"ui:hidden": True})


class MinimaxDeleteVideoConfig(_VideoTask):
    """Cancel a queued H3 task or delete a completed task."""
    operation: Literal["delete_video_task"] = Field("delete_video_task", json_schema_extra={"ui:hidden": True})


class MinimaxListVideoConfig(_Input):
    """List one page of H3 tasks with optional status and model filters."""
    operation: Literal["list_video_tasks"] = Field("list_video_tasks", json_schema_extra={"ui:hidden": True})
    page_num: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"] | None = None
    model: str | None = None
    task_type: Literal["generation", "h3_context_ir", "regeneration"] | None = None


MinimaxConfig = Annotated[Union[
    MinimaxListModelsConfig, MinimaxGetModelConfig, MinimaxListFilesConfig,
    MinimaxGetFileConfig, MinimaxDeleteFileConfig, MinimaxChatConfig,
    MinimaxImageConfig, MinimaxMusicConfig, MinimaxLyricsConfig,
    MinimaxSpeechConfig, MinimaxAsyncSpeechConfig, MinimaxGetSpeechTaskConfig,
    MinimaxListVoicesConfig, MinimaxDeleteVoiceConfig, MinimaxDesignVoiceConfig,
    MinimaxCloneVoiceConfig, MinimaxCreateVideoConfig, MinimaxGetVideoConfig,
    MinimaxDeleteVideoConfig, MinimaxListVideoConfig,
], Field(discriminator="operation")]


class MinimaxNodeConfig(NodeConfig[MinimaxConfig, MinimaxAPIKeyCredential]):
    pass


class MinimaxNode(WorkflowNode):
    integration_type = "automation-minimax"
    connection_evidence = ConnectionEvidence(noun="files", operation="list_files", label_keys=("filename", "file_id"))

    @classmethod
    def get_config_model(cls):
        return MinimaxNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a MiniMax API key")
        op = self.config.config
        action = op.operation
        body = op.model_dump(exclude={"operation"}, exclude_none=True)
        params = None
        method = "POST"
        if action == "list_models":
            method, path, body = "GET", "/v1/models", None
        elif action == "get_model":
            method, path, body = "GET", "/v1/models/" + quote(op.model_id, safe=""), None
        elif action in {"list_files", "get_file"}:
            method, path, params, body = "GET", "/v1/files/" + ("list" if action == "list_files" else "retrieve"), body, None
        elif action == "delete_file":
            path = "/v1/files/delete"
        elif action == "generate_text":
            path = "/v1/chat/completions"
            body.pop("prompt")
            body.pop("system_prompt", None)
            body["messages"] = ([{"role": "system", "content": op.system_prompt}] if op.system_prompt else []) + [{"role": "user", "content": op.prompt}]
            body["stream"] = False
        elif action == "generate_image":
            path = "/v1/image_generation"
            body["response_format"] = "url"
        elif action == "generate_music":
            path = "/v1/music_generation"
            body.update(stream=False, output_format="url")
        elif action == "generate_lyrics":
            path = "/v1/lyrics_generation"
        elif action in {"generate_speech", "create_speech_task"}:
            path = "/v1/t2a_v2" if action == "generate_speech" else "/v1/t2a_async_v2"
            body["voice_setting"] = {k: body.pop(k) for k in ("voice_id", "speed", "vol", "pitch")}
            if action == "generate_speech":
                body.update(stream=False, output_format="url")
        elif action == "get_speech_task":
            method, path, params, body = "GET", "/v1/query/t2a_async_query_v2", body, None
        elif action in {"list_voices", "delete_voice", "design_voice", "clone_voice"}:
            path = {"list_voices": "/v1/get_voice", "delete_voice": "/v1/delete_voice", "design_voice": "/v1/voice_design", "clone_voice": "/v1/voice_clone"}[action]
        elif action == "create_video_task":
            path = "/v2/video_generation"
            body.pop("prompt")
            body.pop("first_frame_url", None)
            body["content"] = [{"type": "text", "text": op.prompt}]
            if op.first_frame_url:
                body["content"].append({"type": "image_url", "image_url": {"url": op.first_frame_url}, "role": "first_frame"})
                body["ratio"] = "adaptive"
        elif action in {"get_video_task", "delete_video_task"}:
            method = "GET" if action == "get_video_task" else "DELETE"
            path = ("/v2/query/video_generation/" if method == "GET" else "/v2/video_generation/") + quote(op.task_id, safe="")
            body = None
        elif action == "list_video_tasks":
            method, path = "GET", "/v2/query/video_generation"
            params = {({"status": "filter.status", "model": "filter.model", "task_type": "filter.task_type"}.get(k, k)): v for k, v in body.items()}
            body = None
        else:
            raise ValueError("Unsupported MiniMax operation")

        key = self.config.credentials.api_key
        async with httpx.AsyncClient(timeout=180, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "Accept": "application/json"},
                params=params, json=body)
        try:
            data = response.json()
        except ValueError:
            response.raise_for_status()
            raise ValueError("MiniMax returned an unexpected non-JSON response") from None
        if not isinstance(data, dict):
            raise ValueError("MiniMax returned an unexpected JSON response")
        base_resp = data.get("base_resp") or {}
        code = base_resp.get("status_code") if isinstance(base_resp, dict) else None
        if not response.is_success or code not in (None, 0) or data.get("error"):
            message = (base_resp.get("status_msg") if isinstance(base_resp, dict) else None) or data.get("error") or response.reason_phrase
            # Providers can echo inputs in errors: never return the credential.
            output = {"status": "error", "error": str(message).replace(key, "[redacted]"), "http_status": response.status_code}
        else:
            # Voice Design returns hex audio; store it through the shared media seam.
            if action == "design_voice" and data.get("trial_audio"):
                try:
                    audio = bytes.fromhex(data["trial_audio"])
                except (TypeError, ValueError):
                    raise ValueError("MiniMax returned invalid hex preview audio") from None
                data["trial_audio"] = BinaryOutput(data=audio, content_type="audio/mpeg", filename="voice-preview.mp3")
            output = {"status": "success", "data": data}
        await self.emit(output)
        return output
