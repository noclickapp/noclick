"""Typecast API 0.1.2: voice discovery, custom voices and speech generation.

Contract: https://typecast.ai/docs/api-reference/openapi.json
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

Model = Literal["ssfm-v31", "ssfm-v30", "ssfm-v21"]


class TypecastAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Typecast API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://studio.typecast.ai/",
            "x-credential-instructions": "Create an API key in the Typecast API Console and paste it here. NoClick sends it in X-API-KEY to api.typecast.ai. Connecting reads your subscription plan and credit usage.",
        })
    credential_type: Literal["typecast_api_key"] = Field("typecast_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VoiceID(Input):
    voice_id: str = Field(..., min_length=1, max_length=256, description="Typecast voice ID from List Voices or List Custom Voices.")

    @field_validator("voice_id")
    @classmethod
    def identifier(cls, value):
        if value in {".", ".."} or any(c in value for c in "/?#\\") or any(ord(c) < 32 for c in value):
            raise ValueError("Use a single Typecast voice ID")
        return value


class ListVoices(Input):
    """List available voices with localized names, previews and model support."""
    operation: Literal["list_voices"] = "list_voices"
    model: Model | None = None
    gender: Literal["male", "female"] | None = None
    age: Literal["child", "teenager", "young_adult", "middle_age", "elder"] | None = None
    use_cases: str | None = Field(None, description="Use-case keyword, such as Ads.")
    voice_type: Literal["original", "custom"] | None = None


class GetVoice(VoiceID):
    """Get one available voice's metadata, models and emotions."""
    operation: Literal["get_voice"] = "get_voice"


class ListCustomVoices(Input):
    """List the authenticated account's cloned voices and training status."""
    operation: Literal["list_custom_voices"] = "list_custom_voices"


class GetCustomVoice(VoiceID):
    """Get an owned custom voice, including pending or failed training."""
    operation: Literal["get_custom_voice"] = "get_custom_voice"


class DeleteCustomVoice(VoiceID):
    """Permanently delete an owned custom voice and free its slot."""
    operation: Literal["delete_custom_voice"] = "delete_custom_voice"


class RecommendVoices(Input):
    """Find voices matching a style, mood, language or use case."""
    operation: Literal["recommend_voices"] = "recommend_voices"
    query: str = Field(..., min_length=1, max_length=500)
    count: int = Field(5, ge=1, le=10)


class GetSubscription(Input):
    """Read your current plan, credit usage and voice-slot limits."""
    operation: Literal["get_subscription"] = "get_subscription"


class AudioSettings(Input):
    audio_format: Literal["wav", "mp3"] = "wav"
    audio_pitch: int = Field(0, ge=-12, le=12)
    audio_tempo: float = Field(1, ge=0.5, le=2)
    target_lufs: float | None = Field(None, ge=-70, le=0)
    remove_silence_ms: StrictInt | None = Field(None, ge=0, le=1000)


class OutputSettings(AudioSettings):
    volume: int | None = Field(None, ge=0, le=200)

    @model_validator(mode="after")
    def loudness(self):
        if self.volume is not None and self.target_lufs is not None:
            raise ValueError("Use either volume or target_lufs")
        return self


class PresetPrompt(Input):
    emotion_type: Literal["preset"] = "preset"
    emotion_preset: Literal["normal", "sad", "happy", "angry", "whisper", "toneup", "tonedown"] = "normal"
    emotion_intensity: float = Field(1, ge=0, le=2)


class SmartPrompt(Input):
    emotion_type: Literal["smart"] = "smart"
    previous_text: str = Field("", max_length=2000)
    next_text: str = Field("", max_length=2000)


class LegacyPrompt(Input):
    emotion_preset: Literal["normal", "sad", "happy", "angry"] = "normal"
    emotion_intensity: float = Field(1, ge=0, le=2)


class Speech(VoiceID):
    text: str = Field(..., min_length=1, max_length=2000)
    model: Model = "ssfm-v31"
    language: str | None = Field(None, description="ISO 639-3 language code; omitted means auto-detect.")
    prompt: Union[PresetPrompt, SmartPrompt, LegacyPrompt] | None = None

    @field_validator("prompt", mode="before")
    @classmethod
    def prompt_kind(cls, value):
        if isinstance(value, dict):
            kind = value.get("emotion_type")
            prompt_class = {"preset": PresetPrompt, "smart": SmartPrompt}.get(kind)
            if kind is None:
                prompt_class = LegacyPrompt
            if prompt_class is None:
                raise ValueError("Use a preset or smart emotion type")
            return prompt_class.model_validate(value)
        return value

    @model_validator(mode="after")
    def compatible_prompt(self):
        if self.prompt is not None:
            if self.model == "ssfm-v21" and not isinstance(self.prompt, LegacyPrompt):
                raise ValueError("ssfm-v21 uses a legacy emotion prompt without emotion_type")
            if self.model != "ssfm-v21" and isinstance(self.prompt, LegacyPrompt):
                raise ValueError("ssfm-v30 and ssfm-v31 use a preset or smart prompt")
        return self


class TextToSpeech(Speech):
    """Generate a WAV or MP3 audio file from text."""
    operation: Literal["text_to_speech"] = "text_to_speech"
    output: OutputSettings | None = None


class StreamSpeech(Speech):
    """Generate streaming speech, collecting its audio into a workflow file."""
    operation: Literal["stream_speech"] = "stream_speech"
    output: AudioSettings | None = None


class SpeechSegment(Speech):
    type: Literal["tts"] = "tts"
    output: OutputSettings | None = None


class PauseSegment(Input):
    type: Literal["pause"] = "pause"
    duration_seconds: float = Field(..., gt=0, le=10)


class ComposeSpeech(Input):
    """Compose speech with multiple voices and pauses into one audio file."""
    operation: Literal["compose_speech"] = "compose_speech"
    segments: list[Annotated[Union[SpeechSegment, PauseSegment], Field(discriminator="type")]] = Field(..., min_length=1, max_length=50)

    @model_validator(mode="after")
    def bounds(self):
        speech = [s for s in self.segments if isinstance(s, SpeechSegment)]
        if not speech or sum(len(s.text) for s in speech) > 2000:
            raise ValueError("Include speech totaling at most 2000 characters")
        if sum(s.duration_seconds for s in self.segments if isinstance(s, PauseSegment)) > 60:
            raise ValueError("Combined pauses may not exceed 60 seconds")
        if len({s.output.audio_format if s.output else "wav" for s in speech}) != 1:
            raise ValueError("All speech segments must use the same audio format")
        return self


TypecastOperation = Annotated[Union[ListVoices, GetVoice, ListCustomVoices, GetCustomVoice,
    DeleteCustomVoice, RecommendVoices, GetSubscription, TextToSpeech, StreamSpeech, ComposeSpeech], Field(discriminator="operation")]


class TypecastConfig(NodeConfig[TypecastOperation, TypecastAPIKeyCredential]):
    pass


ROUTES = {
    "list_voices": ("GET", "/v3/voices"),
    "get_voice": ("GET", "/v3/voices/{voice_id}"),
    "list_custom_voices": ("GET", "/v1/custom-voices"),
    "get_custom_voice": ("GET", "/v1/custom-voices/{voice_id}"),
    "delete_custom_voice": ("DELETE", "/v1/custom-voices/{voice_id}"),
    "recommend_voices": ("GET", "/v1/voices/recommendations"),
    "get_subscription": ("GET", "/v1/users/me/subscription"),
    "text_to_speech": ("POST", "/v1/text-to-speech"),
    "stream_speech": ("POST", "/v1/text-to-speech/stream"),
    "compose_speech": ("POST", "/v1/text-to-speech/compose"),
}


class TypecastNode(WorkflowNode):
    integration_type = "automation-typecast"
    connection_evidence = ConnectionEvidence(operation="get_subscription", noun="Typecast subscription")

    @classmethod
    def get_config_model(cls):
        return TypecastConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Typecast API key")
        op = self.config.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude={"operation"}, exclude_none=True)
        if "{voice_id}" in path:
            path = path.replace("{voice_id}", quote(values.pop("voice_id"), safe=""))
        async with guarded_async_client(timeout=120, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.typecast.ai" + path,
                headers={"X-API-KEY": self.config.credentials.api_key},
                **({"json": values} if method == "POST" else {"params": values}))
        if response.is_error:
            # Preserve provider rejection text for the shared connection proof seam.
            message = response.text.replace(self.config.credentials.api_key, "[redacted]")[:2000]
            raise ValueError(f"Typecast HTTP {response.status_code}: {message}")
        if response.status_code == 204:
            return {"deleted": True, "voice_id": op.voice_id}
        if method == "POST":
            mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if mime not in {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "application/octet-stream"} or not response.content:
                raise ValueError("Typecast did not return an audio file")
            fmt = "mp3" if mime in {"audio/mpeg", "audio/mp3"} else "wav"
            return {"audio": BinaryOutput(data=response.content, content_type=mime, filename="typecast." + fmt)}
        return {"data": response.json()}
