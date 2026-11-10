"""api.video video and live-stream automation using a pasted project API key.

Routes follow the published api.video v1 OpenAPI contract. Signed webhook
subscriptions use its six documented events and provider-issued signing secret.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase


class VideoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="api.video API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://dashboard.api.video/overview",
            "x-credential-instructions": "Paste your api.video production or sandbox API key from the dashboard. Choose the matching environment. NoClick sends the key as the HTTP Basic username with an empty password. Video imports, encoding and streaming can incur api.video usage charges."})
    credential_type: Literal["video_api_key"] = Field("video_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, json_schema_extra={"ui:widget": "password"})
    environment: Literal["production", "sandbox"] = Field("production", title="Environment")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value, key=True)


class Metadata(BaseModel):
    key: str
    value: str


def text(title, required=False, **kwargs):
    return (str if required else Optional[str], Field(... if required else None, title=title, **kwargs))


def boolean(title):
    return (Optional[bool], Field(None, title=title))


def identifier(title):
    return text(title, True, min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")


PAGE = {"currentPage": (int, Field(1, ge=1, title="Page")), "pageSize": (int, Field(25, ge=1, le=100, title="Page Size"))}
VIDEO_ID = {"videoId": identifier("Video ID")}
LIVE_ID = {"liveStreamId": identifier("Live Stream ID")}
CAPTION_ID = {**VIDEO_ID, "language": text("Caption Language", True, description="IETF language tag, such as en or fr")}
VIDEO_FIELDS = {
    "title": text("Title"), "description": text("Description"), "public": boolean("Public Video"),
    "panoramic": boolean("360 Video"), "mp4Support": boolean("Enable MP4"),
    "playerId": text("Player ID"), "tags": (Optional[list[str]], Field(None, title="Tags", description="Replaces the complete tag list when updating")),
    "metadata": (Optional[list[Metadata]], Field(None, title="Metadata", description="Replaces the complete metadata list when updating")),
    "transcript": boolean("Generate Transcript"), "transcriptSummary": boolean("Generate Summary"),
}
LIVE_FIELDS = {"name": text("Name"), "public": boolean("Public Stream"), "playerId": text("Player ID")}


@dataclass(frozen=True)
class Operation:
    label: str
    category: str
    method: str
    path: str
    fields: dict
    query: tuple = ()
    body: tuple = ()


OPERATIONS = {
    "list_videos": Operation("List Videos", "Videos", "GET", "/videos", {
        **PAGE, "title": text("Title Filter"), "description": text("Description Filter"),
        "liveStreamId": text("Live Stream ID Filter"),
        "sortBy": (Optional[Literal["title", "createdAt", "publishedAt", "updatedAt"]], Field(None, title="Sort By")),
        "sortOrder": (Optional[Literal["asc", "desc"]], Field(None, title="Sort Order")),
    }, ("currentPage", "pageSize", "title", "description", "liveStreamId", "sortBy", "sortOrder")),
    "get_video": Operation("Get Video", "Videos", "GET", "/videos/{videoId}", VIDEO_ID),
    "create_video": Operation("Create or Import Video", "Videos", "POST", "/videos", {
        **VIDEO_FIELDS, "title": text("Title", True, min_length=1),
        "source": text("Source URL or Video ID", description="Import a video URL or copy a video already in this account; encoding is asynchronous"),
    }, body=(*VIDEO_FIELDS, "source")),
    "update_video": Operation("Update Video", "Videos", "PATCH", "/videos/{videoId}", {**VIDEO_ID, **VIDEO_FIELDS}, body=tuple(VIDEO_FIELDS)),
    "delete_video": Operation("Delete Video", "Videos", "DELETE", "/videos/{videoId}", VIDEO_ID),
    "get_video_status": Operation("Get Video Status", "Videos", "GET", "/videos/{videoId}/status", VIDEO_ID),
    "set_video_thumbnail": Operation("Select Video Thumbnail", "Videos", "PATCH", "/videos/{videoId}/thumbnail", {
        **VIDEO_ID, "timecode": text("Frame Timecode", True, pattern=r"^\d{2}:\d{2}:\d{2}(\.\d{2,3})?$", description="For example 00:01:00.000")}, body=("timecode",)),
    "list_live_streams": Operation("List Live Streams", "Live Streams", "GET", "/live-streams", {
        **PAGE, "name": text("Name Filter"),
        "sortBy": (Optional[Literal["name", "createdAt", "updatedAt"]], Field(None, title="Sort By")),
        "sortOrder": (Optional[Literal["asc", "desc"]], Field(None, title="Sort Order")),
    }, ("currentPage", "pageSize", "name", "sortBy", "sortOrder")),
    "get_live_stream": Operation("Get Live Stream", "Live Streams", "GET", "/live-streams/{liveStreamId}", LIVE_ID),
    "create_live_stream": Operation("Create Live Stream", "Live Streams", "POST", "/live-streams", {
        **LIVE_FIELDS, "name": text("Name", True, min_length=1)}, body=tuple(LIVE_FIELDS)),
    "update_live_stream": Operation("Update Live Stream", "Live Streams", "PATCH", "/live-streams/{liveStreamId}", {**LIVE_ID, **LIVE_FIELDS}, body=tuple(LIVE_FIELDS)),
    "delete_live_stream": Operation("Delete Live Stream", "Live Streams", "DELETE", "/live-streams/{liveStreamId}", LIVE_ID),
    "complete_live_stream": Operation("Complete Live Stream", "Live Streams", "PUT", "/live-streams/{liveStreamId}/complete", LIVE_ID),
    "list_captions": Operation("List Video Captions", "Captions", "GET", "/videos/{videoId}/captions", {**VIDEO_ID, **PAGE}, ("currentPage", "pageSize")),
    "get_caption": Operation("Get Caption", "Captions", "GET", "/videos/{videoId}/captions/{language}", CAPTION_ID),
    "delete_caption": Operation("Delete Caption", "Captions", "DELETE", "/videos/{videoId}/captions/{language}", CAPTION_ID),
    "list_upload_tokens": Operation("List Upload Tokens", "Upload Tokens", "GET", "/upload-tokens", PAGE, ("currentPage", "pageSize")),
    "create_upload_token": Operation("Create Upload Token", "Upload Tokens", "POST", "/upload-tokens", {
        "ttl": (int, Field(3600, ge=0, le=2147483647, title="Lifetime in Seconds", description="0 creates a token without expiration"))}, body=("ttl",)),
    "delete_upload_token": Operation("Delete Upload Token", "Upload Tokens", "DELETE", "/upload-tokens/{uploadToken}", {"uploadToken": identifier("Upload Token")}),
}


def _model(name, spec):
    return create_model("Video" + "".join(word.title() for word in name.split("_")) + "Config", __module__=__name__,
        __config__=ConfigDict(extra="forbid"),
        operation=(Literal[name], Field(name, title=spec.label, json_schema_extra={
            "const": name, "ui:hidden": True, "x-display-name": spec.label, "x-category": spec.category, "x-is-trigger": False})),
        **spec.fields)


CONFIG_MODELS = {name: _model(name, spec) for name, spec in OPERATIONS.items()}
EVENTS = {
    "on_video_encoding_completed": "video.encoding.quality.completed",
    "on_live_stream_started": "live-stream.broadcast.started",
    "on_live_stream_ended": "live-stream.broadcast.ended",
    "on_video_source_recorded": "video.source.recorded",
    "on_video_caption_generated": "video.caption.generated",
    "on_video_summary_generated": "video.summary.generated",
}
TRIGGER_MODELS = {}
for _name, _event in EVENTS.items():
    _label = _name.replace("_", " ").title()
    TRIGGER_MODELS[_name] = create_model("Video" + _label.replace(" ", "") + "Config", __base__=WebhookTriggerConfigBase, __module__=__name__,
        operation=(Literal[_name], Field(_name, title=_label, json_schema_extra={
            "const": _name, "ui:hidden": True, "x-display-name": _label, "x-category": "Triggers", "x-is-trigger": True})),
        webhook_url=(Optional[str], Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})))
globals().update({model.__name__: model for model in (*CONFIG_MODELS.values(), *TRIGGER_MODELS.values())})
VideoConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + tuple(TRIGGER_MODELS.values())], Field(discriminator="operation")]


class VideoNodeConfig(NodeConfig[VideoConfig, VideoAPIKeyCredential]):
    pass


class VideoNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-video"
    connection_evidence = ConnectionEvidence(operation="list_videos", noun="videos")

    @classmethod
    def get_config_model(cls):
        return VideoNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        credential = VideoAPIKeyCredential.model_validate(credential)
        base = "https://ws.api.video" if credential.environment == "production" else "https://sandbox.api.video"
        auth = base64.b64encode((credential.api_key + ":").encode()).decode()
        async with httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, base + path, headers={"Authorization": "Basic " + auth, "Accept": "application/json"}, params=params, json=body)
        if response.is_error or response.is_redirect:
            try:
                detail = response.json().get("title") or "Request failed"
            except (ValueError, AttributeError):
                detail = "Unexpected provider response"
            detail = str(detail).replace(credential.api_key, "[redacted]").replace(auth, "[redacted]")
            raise ValueError(f"api.video API error {response.status_code}: {detail}")
        return response.json() if response.content else {"acknowledged": True}

    async def execute(self, inputs):
        if self.config.credentials is None:
            raise ValueError("Connect an api.video API key")
        op = self.config.config
        if op.operation in EVENTS:
            payload = self.node_data.get("config", {}).get("_triggerPayload")
            return payload if isinstance(payload, dict) else self.no_event_output(op.operation)
        spec = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        path = spec.path
        for field in re.findall(r"\{(\w+)\}", path):
            path = path.replace("{" + field + "}", quote(str(values[field]), safe=""))
        params = {k: values[k] for k in spec.query if k in values}
        body = {k: values[k] for k in spec.body if k in values} if spec.body else None
        if spec.method == "PATCH" and not body:
            raise ValueError("Provide at least one field to update")
        data = await self._request(self.config.credentials.model_dump(), spec.method, path, params=params or None, body=body)
        return {"status": "success", "operation": op.operation, "data": data}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = EVENTS.get(config.get("operation"))
        if event is None:
            raise ValueError("Choose an api.video trigger")
        data = await cls._request(credential, "POST", "/webhooks", body={"events": [event], "url": webhook_url})
        webhook_id, secret = data.get("webhookId"), data.get("signatureSecret")
        if not webhook_id:
            raise ValueError("api.video did not return a webhook ID")
        if not secret:
            # Older create examples omit the secret; the documented retrieve operation also returns it.
            data = await cls._request(credential, "GET", "/webhooks/" + quote(str(webhook_id), safe=""))
            secret = data.get("signatureSecret")
        if not secret:
            # Avoid leaving an unverified subscription after a failed activation.
            await cls._request(credential, "DELETE", "/webhooks/" + quote(str(webhook_id), safe=""))
            raise ValueError("api.video did not return a webhook signing secret")
        return {"external_webhook_id": str(webhook_id), "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if credential and config.get("external_webhook_id"):
            await cls._request(credential, "DELETE", "/webhooks/" + quote(str(config["external_webhook_id"]), safe=""))

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = config.get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "x-api-video-signature"), "")
        if not isinstance(secret, str) or not secret or not isinstance(signature, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", signature):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature.lower(), expected)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get("type") == EVENTS.get(config.get("operation"))

    @classmethod
    def resolve_agent_event(cls, output):
        kind = output.get("type")
        if kind not in EVENTS.values():
            return super().resolve_agent_event(output)
        if kind.startswith("live-stream."):
            identifier = output.get("liveStreamId")
            text = f"api.video: live stream {identifier} broadcast {'started' if kind.endswith('started') else 'ended'}."
            action = f"Use get_live_stream with liveStreamId={identifier}."
        else:
            identifier = output.get("videoId")
            if kind == "video.encoding.quality.completed":
                text = f"api.video: video {identifier} finished encoding {output.get('encoding')} at {output.get('quality')}. This quality is ready; other renditions may still be encoding."
            elif kind == "video.source.recorded":
                text = f"api.video: live stream {output.get('liveStreamId')} was recorded as video {identifier} and is queued for transcoding."
            elif kind == "video.caption.generated":
                text = f"api.video: caption {output.get('captionId')} ({output.get('language')}, {output.get('generationMode')}) was generated for video {identifier}."
            else:
                text = f"api.video: summary {output.get('summaryId')} was generated for video {identifier}."
            action = f"Use get_video or get_video_status with videoId={identifier}."
        return {"text": f"{text}\nOccurred at {output.get('emittedAt')}.\n{action}", "title": f"api.video {kind}", "conversation_key": str(identifier)}
