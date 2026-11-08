"""Gladia v2 job automation, pinned to the provider's published Control API.

Each operation makes one API request. Job creation is asynchronous: an accepted
job is not a completed transcription, and deletion acknowledgements are not
proof of eventual absence. Live audio streaming belongs to the returned socket.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional, Union
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.gladia.io"


def _audio_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Provide an HTTP or HTTPS audio URL without embedded credentials")
    return value


class GladiaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Gladia API Key", hide_input_in_errors=True, extra="ignore",
        json_schema_extra={
            "x-credential-url": "https://app.gladia.io/apikeys",
            "x-credential-instructions": "Copy an API key from Gladia's API keys page. NoClick sends it in the x-gladia-key header to api.gladia.io. Connecting reads your pre-recorded jobs; it does not create a transcription or prove write permissions.",
        })
    credential_type: Literal["gladia_api_key"] = Field("gladia_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class UploadAudio(_Input):
    """Import an audio or video URL into Gladia's file storage."""
    operation: Literal["upload_audio"] = "upload_audio"
    audio_url: str = Field(..., min_length=1, max_length=8192, description="Publicly accessible audio or video URL; Gladia downloads the media.", json_schema_extra={"format": "uri"})
    _url = field_validator("audio_url")(_audio_url)


class CreatePreRecorded(_Input):
    """Submit a transcription with optional speaker, subtitle and intelligence features."""
    operation: Literal["create_pre_recorded"] = "create_pre_recorded"
    audio_url: str = Field(..., min_length=1, max_length=8192, description="A Gladia upload URL or publicly accessible audio/video URL.", json_schema_extra={"format": "uri"})
    model: Literal["solaria-1", "solaria-3", "solaria-fusion"] = "solaria-1"
    diarization: StrictBool = False
    subtitles: StrictBool = False
    summarization: StrictBool = False
    sentiment_analysis: StrictBool = False
    named_entity_recognition: StrictBool = False
    sentences: StrictBool = False
    custom_metadata: Optional[dict] = Field(None, description="JSON metadata attached to this job.")
    _url = field_validator("audio_url")(_audio_url)


class _Page(_Input):
    offset: int = Field(0, ge=0, le=1_000_000, description="Page offset. Use next_offset when present; otherwise inspect data.next.")
    limit: int = Field(20, ge=1, le=100, description="Maximum jobs in this page; the node does not auto-paginate.")
    status: Optional[list[Literal["queued", "processing", "done", "error"]]] = Field(None, max_length=4)
    before_date: Optional[datetime] = None
    after_date: Optional[datetime] = None


class ListPreRecorded(_Page):
    """List this account's pre-recorded jobs and their processing states."""
    operation: Literal["list_pre_recorded"] = "list_pre_recorded"


class _Job(_Input):
    job_id: str = Field(..., description="The job ID returned by Gladia.", json_schema_extra={"format": "uuid"})

    @field_validator("job_id")
    @classmethod
    def job(cls, value):
        try:
            return str(UUID(value))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Use a Gladia job UUID") from None


class GetPreRecorded(_Job):
    """Get a pre-recorded job's state and transcript when it is done."""
    operation: Literal["get_pre_recorded"] = "get_pre_recorded"


class DeletePreRecorded(_Job):
    """Request deletion of a pre-recorded transcription and its stored data."""
    operation: Literal["delete_pre_recorded"] = "delete_pre_recorded"


class CreateLiveSession(_Input):
    """Create a live session; send audio separately to its returned WebSocket URL."""
    operation: Literal["create_live_session"] = "create_live_session"
    region: Optional[Literal["us-west", "eu-west"]] = None
    encoding: Literal["wav/pcm", "wav/alaw", "wav/ulaw"] = "wav/pcm"
    bit_depth: Literal[8, 16, 24, 32] = 16
    sample_rate: Literal[8000, 16000, 32000, 44100, 48000] = 16000
    channels: int = Field(1, ge=1, le=8)
    endpointing: float = Field(0.05, ge=0.01, le=10)
    maximum_duration_without_endpointing: float = Field(5, ge=5, le=60)
    custom_metadata: Optional[dict] = None


class ListLiveSessions(_Page):
    """List this account's live sessions, including their processing states."""
    operation: Literal["list_live_sessions"] = "list_live_sessions"


class GetLiveSession(_Job):
    """Get a live session's state and available transcript results."""
    operation: Literal["get_live_session"] = "get_live_session"


class DeleteLiveSession(_Job):
    """Request deletion of a live session and its stored audio and transcript."""
    operation: Literal["delete_live_session"] = "delete_live_session"


class ListHistory(_Page):
    """List job history across pre-recorded and live transcription."""
    operation: Literal["list_history"] = "list_history"
    kind: Optional[list[Literal["pre-recorded", "live"]]] = Field(None, max_length=2)


GladiaOperation = Annotated[Union[
    UploadAudio, CreatePreRecorded, ListPreRecorded, GetPreRecorded, DeletePreRecorded,
    CreateLiveSession, ListLiveSessions, GetLiveSession, DeleteLiveSession, ListHistory,
], Field(discriminator="operation")]


class GladiaNodeConfig(NodeConfig[GladiaOperation, GladiaAPIKeyCredential]):
    pass


# Explicit routes keep every user operation tied to one published endpoint.
ROUTES = {
    "upload_audio": ("POST", "/v2/upload"),
    "create_pre_recorded": ("POST", "/v2/pre-recorded"),
    "list_pre_recorded": ("GET", "/v2/pre-recorded"),
    "get_pre_recorded": ("GET", "/v2/pre-recorded/{id}"),
    "delete_pre_recorded": ("DELETE", "/v2/pre-recorded/{id}"),
    "create_live_session": ("POST", "/v2/live"),
    "list_live_sessions": ("GET", "/v2/live"),
    "get_live_session": ("GET", "/v2/live/{id}"),
    "delete_live_session": ("DELETE", "/v2/live/{id}"),
    "list_history": ("GET", "/v1/history"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class GladiaNode(WorkflowNode):
    integration_type = "automation-gladia"
    connection_evidence = ConnectionEvidence(noun="pre-recorded jobs", operation="list_pre_recorded", label_keys=("id",))

    @classmethod
    def get_config_model(cls):
        return GladiaNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Gladia API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        action = op.operation
        method, path = ROUTES[action]
        if isinstance(op, _Job):
            path = path.replace("{id}", op.job_id)
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation", "job_id"})
        params, body = None, None
        if isinstance(op, _Page):
            params = values
        elif isinstance(op, CreateLiveSession):
            region = values.pop("region", None)
            params = {"region": region} if region else None
            body = values
        elif method == "POST":
            body = values
        try:
            async with guarded_async_client(timeout=120, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, params=params, json=body,
                    headers={"x-gladia-key": secret, "Accept": "application/json"})
        except httpx.HTTPError:
            raise ValueError("Gladia request did not complete; inspect job history before retrying a write") from None
        if response.status_code >= 400:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:1000]
            result = {"status": "error", "http_status": response.status_code, "error": _redact(detail, secret)}
        elif response.status_code not in ({202} if method == "DELETE" else {201} if action.startswith("create_") else {200}):
            raise ValueError("Gladia returned an unexpected HTTP status")
        elif method == "DELETE":
            result = {"status": "success", "http_status": 202, "job_id": op.job_id,
                      "deletion_acknowledged": True, "absence_verified": False}
        else:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Gladia returned an unexpected JSON envelope")
            result = {"status": "success", "http_status": response.status_code, "data": payload}
            if isinstance(op, _Page):
                if not isinstance(payload.get("items"), list):
                    raise ValueError("Gladia returned an invalid job list")
                following = payload.get("next")
                next_offset = None
                if following is not None:
                    parsed = urlsplit(following)
                    # The contract types next only as a URI. Preserve it as
                    # provider data, never follow it or forward the API key.
                    # Offer a usable offset only for a recognisable API link.
                    if parsed.scheme == "https" and parsed.netloc == "api.gladia.io":
                        try:
                            candidate = int(parse_qs(parsed.query)["offset"][0])
                            if op.offset < candidate <= 1_000_000:
                                next_offset = candidate
                        except (KeyError, ValueError, IndexError):
                            pass
                result.update(items=payload["items"], next_offset=next_offset, has_more=following is not None)
            elif action.startswith("create_"):
                result["processing_complete"] = False
        result = _redact(result, secret)
        await self.emit(result)
        return result
