"""AssemblyAI pre-recorded transcription API workflow node.

API reference: https://www.assemblyai.com/docs/pre-recorded-audio/api-reference
"""

import asyncio
import base64
import binascii
import json
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence


class AssemblyAIAPIKeyCredential(BaseModel):
    credential_type: Literal["assemblyai_api_key"] = Field(
        "assemblyai_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="AssemblyAI API Key", json_schema_extra={
        "x-credential-url": "https://www.assemblyai.com/dashboard/api-keys",
        "x-credential-instructions": "Create a project API key in the AssemblyAI dashboard and paste it here.",
    })


# AssemblyAI's own MCP server: agents get its tools through a person's AssemblyAI sign-in.
AssemblyaiMcpCredential = mcp_credential("assemblyai", "https://mcp.assemblyai.com/mcp", app="AssemblyAI")
AssemblyAICredential = Union[AssemblyAIAPIKeyCredential, AssemblyaiMcpCredential]


def operation_field(name: str, category: str, label: str):
    return Field(name, title=label, json_schema_extra={
        "const": name, "ui:hidden": True, "x-category": category,
        "x-is-trigger": False, "x-display-name": label,
    })


def parse_array_field(value: Any) -> Any:
    """The generated config form sends array input as JSON text."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("Enter a JSON array, such as [\"one\", \"two\"]") from exc
    return value


class AssemblyAIListTranscriptsConfig(BaseModel):
    model_config = ConfigDict(title="List Transcripts")
    operation: Literal["list_transcripts"] = operation_field("list_transcripts", "Transcripts", "List Transcripts")
    limit: int = Field(10, ge=1, le=100, title="Page Size")
    status: Optional[Literal["queued", "processing", "completed", "error"]] = Field(None, title="Status")
    after_id: Optional[str] = Field(None, title="After Transcript ID")
    before_id: Optional[str] = Field(None, title="Before Transcript ID")


class AssemblyAIGetTranscriptConfig(BaseModel):
    model_config = ConfigDict(title="Get Transcript")
    operation: Literal["get_transcript"] = operation_field("get_transcript", "Transcripts", "Get Transcript")
    transcript_id: str = Field(..., title="Transcript ID")


class AssemblyAISubmitTranscriptConfig(BaseModel):
    model_config = ConfigDict(title="Submit Transcription")
    operation: Literal["submit_transcript"] = operation_field("submit_transcript", "Transcripts", "Submit Transcription")
    audio_url: str = Field(..., title="Audio URL", description="Public or AssemblyAI upload URL of an audio/video file")
    speech_models: List[str] = Field(default_factory=lambda: ["universal-3-5-pro", "universal-2"], title="Speech Models", description="JSON array of models in priority order, e.g. [\"universal-3-5-pro\", \"universal-2\"]")
    language_code: Optional[str] = Field(None, title="Language Code")
    language_detection: bool = Field(False, title="Detect Language")
    speaker_labels: bool = Field(False, title="Speaker Labels")
    speakers_expected: Optional[int] = Field(None, ge=1, title="Expected Speakers")
    punctuate: Optional[bool] = Field(None, title="Punctuate")
    format_text: Optional[bool] = Field(None, title="Format Text")
    keyterms_prompt: Optional[List[str]] = Field(None, title="Key Terms")
    prompt: Optional[str] = Field(None, title="Transcription Prompt", json_schema_extra={"ui:widget": "textarea"})
    webhook_url: Optional[str] = Field(None, title="Webhook URL")
    redact_pii: bool = Field(False, title="Redact PII")
    redact_pii_policies: Optional[List[str]] = Field(None, title="PII Policies")
    redact_pii_audio: bool = Field(False, title="Redact PII Audio")

    @field_validator("speech_models", "keyterms_prompt", "redact_pii_policies", mode="before")
    @classmethod
    def parse_lists(cls, value: Any) -> Any:
        return parse_array_field(value)

    @model_validator(mode="after")
    def validate_options(self):
        if self.language_code and self.language_detection:
            raise ValueError("Use a language code or language detection, not both")
        if self.redact_pii_audio and not self.redact_pii:
            raise ValueError("Audio redaction requires Redact PII")
        if not self.speech_models:
            raise ValueError("At least one speech model is required")
        return self


class AssemblyAITranscribeAndWaitConfig(AssemblyAISubmitTranscriptConfig):
    model_config = ConfigDict(title="Transcribe and Wait")
    operation: Literal["transcribe_and_wait"] = operation_field("transcribe_and_wait", "Transcripts", "Transcribe and Wait")
    max_wait_seconds: int = Field(180, ge=10, le=600, title="Maximum Wait (seconds)")
    poll_interval_seconds: int = Field(3, ge=1, le=30, title="Poll Interval (seconds)")


class AssemblyAIUploadAudioConfig(BaseModel):
    model_config = ConfigDict(title="Upload Audio")
    operation: Literal["upload_audio"] = operation_field("upload_audio", "Audio", "Upload Audio")
    audio_base64: str = Field(
        ..., min_length=4,
        pattern=r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$",
        title="Base64 Audio", description="Base64-encoded media bytes, up to 20 MB",
    )


class AssemblyAIGetSentencesConfig(BaseModel):
    model_config = ConfigDict(title="Get Transcript Sentences")
    operation: Literal["get_sentences"] = operation_field("get_sentences", "Transcript Results", "Get Sentences")
    transcript_id: str = Field(..., title="Transcript ID")


class AssemblyAIGetParagraphsConfig(BaseModel):
    model_config = ConfigDict(title="Get Transcript Paragraphs")
    operation: Literal["get_paragraphs"] = operation_field("get_paragraphs", "Transcript Results", "Get Paragraphs")
    transcript_id: str = Field(..., title="Transcript ID")


class AssemblyAIGetSubtitlesConfig(BaseModel):
    model_config = ConfigDict(title="Get Subtitles")
    operation: Literal["get_subtitles"] = operation_field("get_subtitles", "Transcript Results", "Get Subtitles")
    transcript_id: str = Field(..., title="Transcript ID")
    format: Literal["srt", "vtt"] = Field("srt", title="Subtitle Format")
    chars_per_caption: Optional[int] = Field(None, ge=1, title="Characters per Caption")


class AssemblyAIGetRedactedAudioConfig(BaseModel):
    model_config = ConfigDict(title="Get Redacted Audio")
    operation: Literal["get_redacted_audio"] = operation_field("get_redacted_audio", "Transcript Results", "Get Redacted Audio")
    transcript_id: str = Field(..., title="Transcript ID")


class AssemblyAIWordSearchConfig(BaseModel):
    model_config = ConfigDict(title="Search Transcript Words")
    operation: Literal["word_search"] = operation_field("word_search", "Transcript Results", "Search Words")
    transcript_id: str = Field(..., title="Transcript ID")
    words: List[str] = Field(..., min_length=1, title="Words or Phrases", description="JSON array, e.g. [\"NoClick\", \"workflow\"]")

    @field_validator("words", mode="before")
    @classmethod
    def parse_words(cls, value: Any) -> Any:
        return parse_array_field(value)


class AssemblyAIDeleteTranscriptConfig(BaseModel):
    model_config = ConfigDict(title="Delete Transcript")
    operation: Literal["delete_transcript"] = operation_field("delete_transcript", "Transcripts", "Delete Transcript")
    transcript_id: str = Field(..., title="Transcript ID")


AssemblyAIConfig = Annotated[Union[
    AssemblyAIListTranscriptsConfig,
    AssemblyAIGetTranscriptConfig,
    AssemblyAISubmitTranscriptConfig,
    AssemblyAITranscribeAndWaitConfig,
    AssemblyAIUploadAudioConfig,
    AssemblyAIGetSentencesConfig,
    AssemblyAIGetParagraphsConfig,
    AssemblyAIGetSubtitlesConfig,
    AssemblyAIGetRedactedAudioConfig,
    AssemblyAIWordSearchConfig,
    AssemblyAIDeleteTranscriptConfig,
], Discriminator("operation")]


class AssemblyAINodeConfig(NodeConfig[AssemblyAIConfig, AssemblyAICredential]):
    pass


class AssemblyAINode(WorkflowNode):
    """Pre-recorded transcription, upload, retrieval, search and deletion."""

    integration_type = "automation-assemblyai"

    credential_provider_labels = {"assemblyai": "AssemblyAI Account"}

    edit_examples = [
        "Transcribe this interview and identify each speaker",
        "Find mentions of a product in a completed transcript",
        "Generate SRT subtitles from this transcript",
    ]
    connection_evidence = ConnectionEvidence(
        operation="list_transcripts", noun="recent transcripts", label_keys=("id",),
    )

    @classmethod
    def get_config_model(cls):
        return AssemblyAINodeConfig

    async def _request(self, method: str, path: str, credentials: AssemblyAIAPIKeyCredential,
                       *, params: Optional[Dict[str, Any]] = None,
                       json_data: Optional[Dict[str, Any]] = None,
                       content: Optional[bytes] = None) -> Union[Dict[str, Any], str]:
        base = "https://api.assemblyai.com/v2"
        headers = {"Authorization": credentials.api_key}
        if content is not None:
            headers["Content-Type"] = "application/octet-stream"
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.request(method, f"{base}/{path}", headers=headers,
                                            params=params, json=json_data, content=content)
        if response.is_error:
            try:
                detail = response.json().get("error", response.reason_phrase)
            except (ValueError, AttributeError):
                detail = response.reason_phrase
            raise ValueError(f"AssemblyAI API error {response.status_code}: {detail}")
        if response.status_code == 204:
            return {"success": True, "status_code": 204}
        if "application/json" in response.headers.get("content-type", ""):
            return response.json()
        return response.text

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        node_config = self.config
        if not isinstance(node_config, AssemblyAINodeConfig):
            raise ValueError("AssemblyAI requires valid configuration")
        credentials = node_config.credentials
        if not credentials or not credentials.api_key:
            raise ValueError("Connect an AssemblyAI API key first")
        config = node_config.config
        op = config.operation
        if op == "list_transcripts":
            params = config.model_dump(exclude={"operation"}, exclude_none=True)
            return await self._request("GET", "transcript", credentials, params=params)
        if op in {"submit_transcript", "transcribe_and_wait"}:
            payload = config.model_dump(exclude={"operation", "max_wait_seconds", "poll_interval_seconds"}, exclude_none=True)
            # Disabled features can be omitted; explicit False for formatting controls must be sent.
            for feature in ("language_detection", "speaker_labels", "redact_pii", "redact_pii_audio"):
                if payload.get(feature) is False:
                    payload.pop(feature)
            result = await self._request("POST", "transcript", credentials, json_data=payload)
            if op == "submit_transcript":
                return result
            transcript_id = result["id"]
            loop = asyncio.get_running_loop()
            deadline = loop.time() + config.max_wait_seconds
            while True:
                current = await self._request("GET", f"transcript/{quote(transcript_id, safe='')}", credentials)
                if current.get("status") == "completed":
                    return current
                if current.get("status") == "error":
                    raise ValueError(f"AssemblyAI transcription failed: {current.get('error', 'unknown error')}")
                if loop.time() >= deadline:
                    return {"id": transcript_id, "status": current.get("status"), "timed_out": True}
                await asyncio.sleep(min(config.poll_interval_seconds, max(0, deadline - loop.time())))
        if op == "upload_audio":
            try:
                audio = base64.b64decode(config.audio_base64, validate=True)
            except binascii.Error as exc:
                raise ValueError("Base64 Audio must contain valid base64 bytes") from exc
            if not audio or len(audio) > 20 * 1024 * 1024:
                raise ValueError("Audio must be between 1 byte and 20 MB")
            return await self._request("POST", "upload", credentials, content=audio)
        transcript_id = quote(config.transcript_id, safe="")
        path = f"transcript/{transcript_id}"
        if op == "get_transcript":
            return await self._request("GET", path, credentials)
        if op == "get_sentences":
            return await self._request("GET", f"{path}/sentences", credentials)
        if op == "get_paragraphs":
            return await self._request("GET", f"{path}/paragraphs", credentials)
        if op == "get_subtitles":
            params = {"chars_per_caption": config.chars_per_caption} if config.chars_per_caption else None
            result = await self._request("GET", f"{path}/{config.format}", credentials, params=params)
            return {"id": config.transcript_id, "format": config.format, "subtitles": result}
        if op == "get_redacted_audio":
            return await self._request("GET", f"{path}/redacted-audio", credentials)
        if op == "word_search":
            return await self._request("GET", f"{path}/word-search", credentials,
                                       params={"words": ",".join(config.words)})
        if op == "delete_transcript":
            return await self._request("DELETE", path, credentials)
        raise ValueError(f"Unsupported AssemblyAI operation: {op}")
