"""Elai v1 video automation, using a manually supplied workspace API token.

Routes and payloads follow Elai's published OpenAPI 1.0 contract. Each action
makes one provider request; render acceptance is explicitly not completion.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://apis.elai.io/api/v1"
DOCS = "https://elai.readme.io/reference/"


class ElaiAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Elai API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.elai.io/",
        "x-credential-instructions": "In Elai, open your workspace API settings and copy the API token. Paste the token without the Bearer prefix. NoClick checks the current workspace admin with GET /users/me.",
    })
    credential_type: Literal["elai_api_token"] = Field("elai_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API token, without Bearer or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


ResourceID = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


class GetCurrentUser(_Input):
    """Read the admin, workspace, organization, plan and minute balance."""
    operation: Literal["get_current_user"] = "get_current_user"


class ListVideos(_Input):
    """Read a page of videos. Continue with page + 1 until page equals pages."""
    operation: Literal["list_videos"] = "list_videos"
    page: int = Field(1, ge=1)
    limit: int = Field(50, ge=1, le=100)
    status: list[Literal["draft", "validating", "rendering", "moderation", "error", "ready"]] | None = None
    tags: list[str] | None = None
    sort: list[Literal["+name", "-name", "+createdAt", "-createdAt", "+updatedAt", "-updatedAt"]] | None = None
    type: Literal["template"] | None = None
    deleted: bool | None = Field(None, description="Omit to include deleted and non-deleted videos; false excludes deleted videos.")


class _Video(_Input):
    video_id: ResourceID


class GetVideo(_Video):
    """Read a video, including slides and render status."""
    operation: Literal["get_video"] = "get_video"


class DeleteVideo(_Video):
    """Delete the selected video."""
    operation: Literal["delete_video"] = "delete_video"


class RenderVideo(_Video):
    """Queue rendering. Acceptance does not mean an MP4 is ready; poll Get Video."""
    operation: Literal["render_video"] = "render_video"


class Slide(_Input):
    id: int
    animation: str = "fade_in"
    language: str = "English"
    speech: str
    voiceType: Literal["text", "file", "silence"] = "text"
    voice: str = "en-US-AriaNeural"
    voiceProvider: str = "azure"
    canvas: dict | None = Field(None, description="Optional Elai canvas object with background, version and objects.")
    avatar: dict | None = Field(None, description="Optional avatar object with code and gender.")


class CreateVideo(_Input):
    """Create a video from prepared slides; rendering is a separate action."""
    operation: Literal["create_video"] = "create_video"
    name: str = Field(..., min_length=1)
    slides: list[Slide] = Field(..., min_length=1)
    tags: list[str] | None = None
    public: bool | None = None
    folderId: ResourceID | None = None


class UpdateVideo(_Video):
    """Update a video's name, tags or public-link visibility."""
    operation: Literal["update_video"] = "update_video"
    name: str | None = None
    tags: list[str] | None = None
    public: bool | None = None

    @model_validator(mode="after")
    def changed(self):
        if all(getattr(self, key) is None for key in ("name", "tags", "public")):
            raise ValueError("Supply a name, tags or public visibility to update")
        return self


class CopyVideo(_Input):
    """Copy a video or template into a new video."""
    operation: Literal["copy_video"] = "copy_video"
    sourceId: ResourceID
    folderId: ResourceID | None = None
    createTemplate: bool | None = None


class Language(_Input):
    code: str = Field(..., min_length=1, description="Locale from the voice catalog, for example en-US.")
    name: str = Field(..., min_length=1, description="Language group from the voice catalog, for example English.")
    voices: dict[str, str] | None = None
    displayName: str | None = None


class TranslateVideo(_Video):
    """Translate a video into the selected voice-catalog language and locale."""
    operation: Literal["translate_video"] = "translate_video"
    language: Language


class CreateFromText(_Input):
    """Create a story video from plain text, HTML or a source URL."""
    operation: Literal["create_from_text"] = "create_from_text"
    source_type: Literal["text", "html"] = "text"
    source: str = Field(..., min_length=1, description="Plain text for text; HTML or a URL for html.")
    folderId: ResourceID | None = None
    tags: list[str] | None = None


class ListVoices(_Input):
    """Read language groups and their supported voices/providers."""
    operation: Literal["list_voices"] = "list_voices"


class ListAvatars(_Input):
    """Read avatars available to the workspace."""
    operation: Literal["list_avatars"] = "list_avatars"
    realtime: bool | None = None


class GetAvatar(_Input):
    """Read an avatar and its variants."""
    operation: Literal["get_avatar"] = "get_avatar"
    avatar_id: ResourceID


class ListTemplates(_Input):
    """Read private workspace templates and the public slide-template catalog."""
    operation: Literal["list_templates"] = "list_templates"


class GetTemplate(_Input):
    """Read a slide template's full content."""
    operation: Literal["get_template"] = "get_template"
    template_id: ResourceID


class ListUploads(_Input):
    """Read a page of media assets. Continue at offset + limit when hasMore."""
    operation: Literal["list_uploads"] = "list_uploads"
    offset: int = Field(0, ge=0)
    limit: int = Field(30, ge=1, le=100)
    q: str | None = Field(None, description="Provider regex search on the asset name.")
    type: Literal["images", "vectors", "videos", "gifs"] | None = None
    uploadFolderId: ResourceID | None = None
    sort: Literal["CREATED_AT_DESCEND", "CREATED_AT_ASCEND", "UPDATED_AT_DESCEND", "UPDATED_AT_ASCEND", "NAME_ASCEND", "NAME_DESCEND"] | None = None


class ListVideoExports(_Video):
    """Read the video's exports to an external destination."""
    operation: Literal["list_video_exports"] = "list_video_exports"
    target: str = "panopto"


class GetVideoHistory(_Video):
    """Read video edit history. Provider failures can time out."""
    operation: Literal["get_video_history"] = "get_video_history"


class ListCustomVoices(_Input):
    """Read custom voices belonging to this workspace."""
    operation: Literal["list_custom_voices"] = "list_custom_voices"


ElaiOperation = Annotated[Union[GetCurrentUser, ListVideos, GetVideo, CreateVideo, UpdateVideo,
    DeleteVideo, RenderVideo, CopyVideo, TranslateVideo, CreateFromText, ListVoices,
    ListAvatars, GetAvatar, ListTemplates, GetTemplate, ListUploads, ListVideoExports,
    GetVideoHistory, ListCustomVoices], Field(discriminator="operation")]


class ElaiConfig(NodeConfig[ElaiOperation, ElaiAPITokenCredential]):
    pass


# Exactly one documented provider operation per NoClick action.
ROUTES = {
    "get_current_user": ("GET", "/users/me"),
    "list_videos": ("GET", "/videos"),
    "get_video": ("GET", "/videos/{video_id}"),
    "create_video": ("POST", "/videos"),
    "update_video": ("PATCH", "/videos/{video_id}"),
    "delete_video": ("DELETE", "/videos/{video_id}"),
    "render_video": ("POST", "/videos/render/{video_id}"),
    "copy_video": ("POST", "/videos/copy"),
    "translate_video": ("POST", "/videos/translate/{video_id}"),
    "create_from_text": ("POST", "/videos/text/{source_type}"),
    "list_voices": ("GET", "/voices"),
    "list_avatars": ("GET", "/avatars"),
    "get_avatar": ("GET", "/avatars/{avatar_id}"),
    "list_templates": ("GET", "/templates"),
    "get_template": ("GET", "/templates/{template_id}"),
    "list_uploads": ("GET", "/uploads"),
    "list_video_exports": ("GET", "/videos/{video_id}/exports"),
    "get_video_history": ("GET", "/videos/history/{video_id}"),
    "list_custom_voices": ("GET", "/voices/user-voices"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {str(key).replace(token, "[redacted]"): _redact(item, token) for key, item in value.items()}
    return value


class ElaiNode(WorkflowNode):
    integration_type = "automation-elai"
    connection_evidence = ConnectionEvidence(noun="Elai workspace admin", identity_operation="get_current_user")

    @classmethod
    def get_config_model(cls):
        return ElaiConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Elai API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, path = ROUTES[op.operation]
        data = op.model_dump(exclude_none=True, exclude={"operation"})
        for key in ("video_id", "avatar_id", "template_id", "source_type"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(data.pop(key), safe=""))
        if op.operation == "create_from_text":
            data["from"] = data.pop("source")
        params = None
        body = None
        if method == "GET":
            params = [(key, str(item).lower() if isinstance(item, bool) else item)
                      for key, value in data.items() for item in (value if isinstance(value, list) else [value])]
        elif data:
            body = data
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    params=params, json=body)
        except httpx.RequestError:
            raise ValueError("Elai request did not complete; check the workspace before retrying a write") from None
        if not 200 <= response.status_code < 300:
            message = "Elai request failed"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"]
            except ValueError:
                pass
            output = {"status": "error", "http_status": response.status_code, "message": message}
        else:
            payload = response.json() if response.content else None
            output = {"status": "success", "action": op.operation, "http_status": response.status_code, "data": payload}
            if op.operation == "render_video":
                output.update(render_completed=False, message="Render queued; poll Get Video for status ready or error.")
            elif op.operation == "delete_video":
                output["deleted_video_id"] = op.video_id
        output = _redact(output, token)
        await self.emit(output)
        return output
