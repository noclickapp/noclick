"""HeyGen External API v1.0.0: fixed v3 routes, one request per operation.

Contract: https://developers.heygen.com/openapi/external-api.json.
Lists return one page and preserve has_more/next_token. Generation returns a job,
not a completed video; poll its corresponding get operation for completion.
"""
import hashlib
import hmac
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE = "https://api.heygen.com"
ResourceID = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]

class HeyGenAPIKey(BaseModel):
    model_config = ConfigDict(title="Heygen API Key", extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.heygen.com/settings?nav=API",
        "x-credential-instructions": "Paste the API key from your HeyGen account settings. NoClick sends it as x-api-key to api.heygen.com. The connection check reads your current user and billing information. Generation consumes HeyGen credits and may require a paid plan. The connection check does not prove access to every operation."})
    credential_type: Literal["heygen_api_key"] = Field("heygen_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the key without a header or whitespace")
        return value

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class Page(Input):
    limit: int = Field(10, ge=1, le=100, description="Results on this page only.")
    token: str | None = Field(None, description="Opaque next_token from the previous response; omit for the first page.")

class Write(Input):
    idempotency_key: str | None = Field(None, min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_:.-]+$", description="Optional Idempotency-Key header. Reuse the same key and body when retrying the same creation.")

class GetCurrentUser(Input):
    """Get current user."""
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})

class CreateVideo(Write):
    """Create an avatar video from a script; returns a queued job, not a finished video."""
    operation: Literal["create_video"] = Field("create_video", json_schema_extra={"ui:hidden": True})
    avatar_id: ResourceID = Field(..., description="Avatar look ID, available from HeyGen's avatar library.")
    script: str = Field(..., min_length=1, description="Text for the avatar to speak.")
    voice_id: ResourceID
    title: str | None = None
    folder_id: ResourceID | None = None
    resolution: Literal["720p", "1080p", "4k"] | None = None
    aspect_ratio: Literal["16:9", "9:16", "4:5", "5:4", "1:1", "auto"] = "16:9"
    callback_id: str | None = None
    callback_url: str | None = None

class ListVideos(Page):
    """List videos."""
    operation: Literal["list_videos"] = Field("list_videos", json_schema_extra={"ui:hidden": True})
    folder_id: ResourceID | None = None
    title: str | None = Field(None, min_length=1)

class GetVideo(Input):
    """Get video."""
    operation: Literal["get_video"] = Field("get_video", json_schema_extra={"ui:hidden": True})
    video_id: ResourceID

class DeleteVideo(Input):
    """Delete video."""
    operation: Literal["delete_video"] = Field("delete_video", json_schema_extra={"ui:hidden": True})
    video_id: ResourceID

class GetTemplate(Input):
    """Get template."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})
    template_id: ResourceID

class GetAvatarGroup(Input):
    """Get avatar group."""
    operation: Literal["get_avatar_group"] = Field("get_avatar_group", json_schema_extra={"ui:hidden": True})
    group_id: ResourceID

class GetVoice(Input):
    """Get voice."""
    operation: Literal["get_voice"] = Field("get_voice", json_schema_extra={"ui:hidden": True})
    voice_id: ResourceID

class GetTranslation(Input):
    """Get translation."""
    operation: Literal["get_translation"] = Field("get_translation", json_schema_extra={"ui:hidden": True})
    video_translation_id: ResourceID

class DeleteTranslation(Input):
    """Delete translation."""
    operation: Literal["delete_translation"] = Field("delete_translation", json_schema_extra={"ui:hidden": True})
    video_translation_id: ResourceID

class GetFolder(Input):
    """Get folder."""
    operation: Literal["get_folder"] = Field("get_folder", json_schema_extra={"ui:hidden": True})
    folder_id: ResourceID

class GetAsset(Input):
    """Get asset."""
    operation: Literal["get_asset"] = Field("get_asset", json_schema_extra={"ui:hidden": True})
    asset_id: ResourceID

class DeleteAsset(Input):
    """Delete asset."""
    operation: Literal["delete_asset"] = Field("delete_asset", json_schema_extra={"ui:hidden": True})
    asset_id: ResourceID

class ListTemplates(Page):
    """List templates."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})

class TextVariable(Input):
    type: Literal["text"] = Field("text", json_schema_extra={"ui:hidden": True})
    content: str = Field(..., max_length=10000)

class GenerateFromTemplate(Write):
    """Generate from template."""
    operation: Literal["generate_from_template"] = Field("generate_from_template", json_schema_extra={"ui:hidden": True})
    template_id: ResourceID
    variables: dict[str, TextVariable] = Field(..., description="Text replacements keyed by the template variable names. Omitted text variables keep their literal placeholders. Other variable kinds keep template values.")
    title: str | None = None
    caption: bool = False
    folder_id: ResourceID | None = None
    callback_id: str | None = None
    callback_url: str | None = None

class ListAvatarGroups(Page):
    """List avatar groups."""
    operation: Literal["list_avatar_groups"] = Field("list_avatar_groups", json_schema_extra={"ui:hidden": True})
    limit: int = Field(20, ge=1, le=50)
    ownership: Literal["public", "private"] | None = None

class ListVoices(Page):
    """List voices."""
    operation: Literal["list_voices"] = Field("list_voices", json_schema_extra={"ui:hidden": True})
    type: Literal["public", "private"] = "public"
    engine: str | None = None
    language: str | None = None
    gender: Literal["male", "female"] | None = None

class VideoURL(Input):
    type: Literal["url"] = Field("url", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, description="Public source video URL fetched by HeyGen.")

class VideoAsset(Input):
    type: Literal["asset_id"] = Field("asset_id", json_schema_extra={"ui:hidden": True})
    asset_id: ResourceID

class CreateTranslation(Write):
    """Create translation."""
    operation: Literal["create_translation"] = Field("create_translation", json_schema_extra={"ui:hidden": True})
    video: Annotated[Union[VideoURL, VideoAsset], Field(discriminator="type")]
    output_languages: list[str] = Field(..., min_length=1, description="Names returned by list_translation_languages, for example English or Spanish (Spain).")
    title: str | None = None
    input_language: str | None = None
    translate_audio_only: bool = False
    mode: Literal["speed", "precision"] = "speed"
    callback_url: str | None = None
    callback_id: str | None = None

class ListTranslations(Page):
    """List translations."""
    operation: Literal["list_translations"] = Field("list_translations", json_schema_extra={"ui:hidden": True})

class ListTranslationLanguages(Input):
    """List translation languages."""
    operation: Literal["list_translation_languages"] = Field("list_translation_languages", json_schema_extra={"ui:hidden": True})

class CreateFolder(Write):
    """Create folder."""
    operation: Literal["create_folder"] = Field("create_folder", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=256)
    parent_id: str | None = Field(None, max_length=64)
    type: Literal["mixed", "video", "video_translate"] = "mixed"

class OnVideoCompleted(WebhookTriggerConfigBase):
    """Start a workflow when HeyGen finishes an avatar video.

    Payload and signature: https://developers.heygen.com/docs/webhook-events
    and https://developers.heygen.com/docs/webhooks.
    """
    operation: Literal["on_video_completed"] = Field("on_video_completed", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers",
        "x-display-name": "Video Completed"})
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered with HeyGen automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})

HeyGenOperation = Annotated[Union[OnVideoCompleted, GetCurrentUser, CreateVideo, ListVideos, GetVideo, DeleteVideo, GetTemplate, GetAvatarGroup, GetVoice, GetTranslation, DeleteTranslation, GetFolder, GetAsset, DeleteAsset, ListTemplates, GenerateFromTemplate, ListAvatarGroups, ListVoices, CreateTranslation, ListTranslations, ListTranslationLanguages, CreateFolder], Field(discriminator="operation")]

class HeyGenConfig(NodeConfig[HeyGenOperation, HeyGenAPIKey]):
    pass

ROUTES = {'get_current_user': ('GET', '/v3/users/me'), 'create_video': ('POST', '/v3/videos'), 'list_videos': ('GET', '/v3/videos'), 'get_video': ('GET', '/v3/videos/{video_id}'), 'delete_video': ('DELETE', '/v3/videos/{video_id}'), 'get_template': ('GET', '/v3/templates/{template_id}'), 'get_avatar_group': ('GET', '/v3/avatars/{group_id}'), 'get_voice': ('GET', '/v3/voices/{voice_id}'), 'get_translation': ('GET', '/v3/video-translations/{video_translation_id}'), 'delete_translation': ('DELETE', '/v3/video-translations/{video_translation_id}'), 'get_folder': ('GET', '/v3/folders/{folder_id}'), 'get_asset': ('GET', '/v3/assets/{asset_id}'), 'delete_asset': ('DELETE', '/v3/assets/{asset_id}'), 'list_templates': ('GET', '/v3/templates'), 'generate_from_template': ('POST', '/v3/templates/{template_id}'), 'list_avatar_groups': ('GET', '/v3/avatars'), 'list_voices': ('GET', '/v3/voices'), 'create_translation': ('POST', '/v3/video-translations'), 'list_translations': ('GET', '/v3/video-translations'), 'list_translation_languages': ('GET', '/v3/video-translations/languages'), 'create_folder': ('POST', '/v3/folders')}

def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()}
    return value

class HeyGenNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-heygen"
    connection_evidence = ConnectionEvidence(noun="HeyGen account", identity_operation="get_current_user", identity_keys=("email", "username"))

    @classmethod
    def get_config_model(cls):
        return HeyGenConfig

    @staticmethod
    async def _webhook_request(credential, method, path, body=None):
        token = (credential or {}).get("api_key")
        if not token:
            raise ValueError("Connect a HeyGen API key before activating this trigger")
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"x-api-key": token, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("HeyGen webhook request could not be completed") from None
        if not response.is_success:
            raise ValueError(f"HeyGen webhook request failed (HTTP {response.status_code})")
        try:
            result = response.json()
        except ValueError:
            raise ValueError("HeyGen returned an invalid webhook response") from None
        if not isinstance(result, dict) or result.get("error") or not isinstance(result.get("data"), dict):
            raise ValueError("HeyGen returned an invalid webhook data envelope")
        return result["data"]

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        if (config or {}).get("operation") != "on_video_completed":
            raise ValueError("Choose the Video Completed trigger")
        endpoint = await cls._webhook_request(credential, "POST", "/v3/webhooks/endpoints",
            {"url": webhook_url, "events": ["avatar_video.success"]})
        endpoint_id, secret = endpoint.get("endpoint_id"), endpoint.get("secret")
        if not isinstance(endpoint_id, str) or not endpoint_id or not isinstance(secret, str) or not secret:
            raise ValueError("HeyGen did not return a webhook endpoint ID and signing secret")
        return {"external_webhook_id": endpoint_id, "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint_id = (config or {}).get("external_webhook_id")
        if endpoint_id:
            await cls._webhook_request(credential, "DELETE",
                "/v3/webhooks/endpoints/" + quote(str(endpoint_id), safe=""))

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # HeyGen uses the whole secret verbatim, including whsec_, and raw bytes.
        secret = (config or {}).get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "signature"), "")
        if not isinstance(secret, str) or not secret or not isinstance(signature, str):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        try:
            supplied = bytes.fromhex(signature)
        except ValueError:
            return False
        return hmac.compare_digest(supplied, bytes.fromhex(expected))

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return (config or {}).get("operation") == "on_video_completed" and payload.get("event_type") == "avatar_video.success"

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if not cls.filter_trigger_payload(payload, config):
            return None
        data = payload.get("event_data")
        if not isinstance(data, dict) or not isinstance(data.get("video_id"), str) or not data["video_id"]:
            raise ValueError("HeyGen video completion did not include a video ID")
        return {"status": "success", "event_type": payload["event_type"], "data": data}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("event_type") != "avatar_video.success":
            return super().resolve_agent_event(output)
        data = output.get("data")
        if not isinstance(data, dict) or not data.get("video_id"):
            return super().resolve_agent_event(output)
        video_id = data["video_id"]
        lines = [f"HeyGen completed avatar video {video_id}."]
        for label, key in (("Video", "video_page_url"), ("Download (expires)", "url"),
                           ("Share", "video_share_page_url"), ("GIF", "gif_download_url"),
                           ("Folder ID", "folder_id"), ("Callback ID", "callback_id")):
            if data.get(key):
                lines.append(f"{label}: {data[key]}")
        lines.append(f"To fetch the current video and fresh download links: get_video video_id={video_id}.")
        return {"text": "\n".join(lines), "conversation_key": str(video_id), "title": f"HeyGen video completed: {video_id}"}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a HeyGen API key")
        config = self.config.config
        if isinstance(config, OnVideoCompleted):
            payload = (self.node_data.get("config") or {}).get("_triggerPayload") or inputs
            result = self.resolve_trigger_payload(payload, config.model_dump())
            if result is None:
                raise ValueError("Waiting for a HeyGen video completion")
            return result
        method, route = ROUTES[config.operation]
        values = config.model_dump(exclude={"operation"}, exclude_none=True)
        for name in ("video_id", "template_id", "group_id", "voice_id", "video_translation_id", "folder_id", "asset_id"):
            if "{" + name + "}" in route:
                route = route.replace("{" + name + "}", quote(values.pop(name), safe=""))
        token = self.config.credentials.api_key
        headers = {"x-api-key": token, "Accept": "application/json"}
        idempotency_key = values.pop("idempotency_key", None)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if config.operation == "create_video":
            values["type"] = "avatar"
        kwargs = {"params": values} if method == "GET" else {"json": values} if method == "POST" else {}
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route, headers=headers, **kwargs)
        except httpx.HTTPError:
            raise ValueError("HeyGen request could not be completed; inspect the provider before retrying a write") from None
        try:
            body = response.json()
        except ValueError:
            raise ValueError("HeyGen returned a non-JSON response; inspect the provider before retrying a write") from None
        if not response.is_success or (isinstance(body, dict) and body.get("error")):
            error = body.get("error") if isinstance(body, dict) else None
            message = error.get("message") if isinstance(error, dict) else error
            return {"status": "error", "http_status": response.status_code, "error": _redact(message if isinstance(message, str) else "HeyGen rejected the request", token)}
        if not isinstance(body, dict) or not isinstance(body.get("data"), (dict, list)):
            raise ValueError("HeyGen returned an invalid data envelope; inspect the provider before retrying a write")
        if config.operation == "get_current_user" and (
            not isinstance(body["data"], dict)
            or not isinstance(body["data"].get("username"), str)
            or not body["data"]["username"].strip()
        ):
            raise ValueError("HeyGen returned no current-user identity")
        if config.operation.startswith("list_") and config.operation != "list_translation_languages" and not isinstance(body["data"], list):
            raise ValueError("HeyGen returned an invalid list envelope")
        return {**_redact(body, token), "status": "success"}
