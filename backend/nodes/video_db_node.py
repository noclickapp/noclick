"""VideoDB Server API 1.0.0. Each operation sends one documented request.

Processing calls return provider job state and IDs; get_async_result reads them
later. Uploads take a public media URL. No automatic retries of writes.
Contract: https://docs.videodb.io/openapi.json
"""
import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class VideoDbAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="VideoDB API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://console.videodb.io",
            "x-credential-instructions": "Copy your VideoDB API key from the VideoDB console. NoClick sends it in the x-access-token header to api.videodb.io. Uploading, indexing, transcription and clip generation can consume VideoDB credits."})
    credential_type: Literal["video_db_api_key"] = Field("video_db_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without a header or whitespace")
        return value


class VideoDbInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def resource_id(cls, value, info):
        if value is not None and info.field_name.endswith("_id"):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,255}", value):
                raise ValueError("Use the VideoDB resource ID without a URL or path")
        return value



class GetAccountConfig(VideoDbInput):
    'Get user information'
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class ListCollectionsConfig(VideoDbInput):
    'Get user collections'
    operation: Literal["list_collections"] = Field("list_collections", json_schema_extra={"ui:hidden": True})


class CreateCollectionConfig(VideoDbInput):
    'Create new collection'
    operation: Literal["create_collection"] = Field("create_collection", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1)
    description: str | None = Field(None, min_length=1)
    is_public: bool | None = Field(None)


class GetCollectionConfig(VideoDbInput):
    'Get collection details'
    operation: Literal["get_collection"] = Field("get_collection", json_schema_extra={"ui:hidden": True})
    collection_id: str = Field(..., min_length=1)


class UpdateCollectionConfig(VideoDbInput):
    'Update collection'
    operation: Literal["update_collection"] = Field("update_collection", json_schema_extra={"ui:hidden": True})
    collection_id: str = Field(..., min_length=1)
    name: str | None = Field(None, min_length=1)
    description: str | None = Field(None, min_length=1)
    is_public: bool | None = Field(None)


class DeleteCollectionConfig(VideoDbInput):
    'Delete collection'
    operation: Literal["delete_collection"] = Field("delete_collection", json_schema_extra={"ui:hidden": True})
    collection_id: str = Field(..., min_length=1)


class UploadMediaConfig(VideoDbInput):
    'Upload media to collection'
    operation: Literal["upload_media"] = Field("upload_media", json_schema_extra={"ui:hidden": True})
    collection_id: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    name: str | None = Field(None, min_length=1)
    media_type: Literal['video', 'audio', 'image'] | None = Field(None, min_length=1)
    callback_url: str | None = Field(None, min_length=1, description='Optional provider callback URL for asynchronous processing.')


class SearchCollectionConfig(VideoDbInput):
    'Search within collection'
    operation: Literal["search_collection"] = Field("search_collection", json_schema_extra={"ui:hidden": True})
    collection_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    index_type: Literal['spoken_word', 'scene'] | None = Field(None, min_length=1)
    search_type: Literal['semantic', 'custom'] | None = Field(None, min_length=1)
    score_threshold: float | None = Field(None)
    result_threshold: int | None = Field(None, ge=1)
    stitch: bool | None = Field(None)
    rerank: bool | None = Field(None)
    filter: list[dict[str, Any]] | None = Field(None)


class ListVideosConfig(VideoDbInput):
    'List videos'
    operation: Literal["list_videos"] = Field("list_videos", json_schema_extra={"ui:hidden": True})
    collection_id: str | None = Field(None, min_length=1)
    page_index: int | None = Field(None, ge=0, description='Zero-based page index. This operation returns one page; increment this for the next page.')
    count: int | None = Field(None, le=5000, ge=1)


class GetVideoConfig(VideoDbInput):
    'Get video details'
    operation: Literal["get_video"] = Field("get_video", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., min_length=1, pattern='^m-')
    collection_id: str | None = Field(None, min_length=1)


class UpdateVideoConfig(VideoDbInput):
    'Update video'
    operation: Literal["update_video"] = Field("update_video", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., min_length=1, pattern='^m-')
    name: str | None = Field(None, min_length=1)


class DeleteVideoConfig(VideoDbInput):
    'Delete video'
    operation: Literal["delete_video"] = Field("delete_video", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., min_length=1, pattern='^m-')


class CreateVideoStreamConfig(VideoDbInput):
    'Create video stream'
    operation: Literal["create_video_stream"] = Field("create_video_stream", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., min_length=1, pattern='^m-')
    format: Literal['mp4', 'webm', 'hls'] | None = Field(None, min_length=1)
    quality: Literal['low', 'medium', 'high'] | None = Field(None, min_length=1)


class GetVideoTranscriptionConfig(VideoDbInput):
    'Get video transcription'
    operation: Literal["get_video_transcription"] = Field("get_video_transcription", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., min_length=1, pattern='^m-')
    engine: str | None = Field(None, min_length=1)
    start: float | None = Field(None)
    end: float | None = Field(None)
    segmenter: str | None = Field(None, min_length=1)
    length: int | None = Field(None, ge=1)


class GenerateVideoTranscriptionConfig(VideoDbInput):
    'Generate video transcription'
    operation: Literal["generate_video_transcription"] = Field("generate_video_transcription", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., min_length=1, pattern='^m-')
    engine: str | None = Field(None, min_length=1)
    force: bool | None = Field(None)
    language_code: str | None = Field(None, min_length=1)
    callback_url: str | None = Field(None, min_length=1, description='Optional provider callback URL for asynchronous processing.')
    callback_data: dict[str, Any] | None = Field(None)


class GetVideoIndexConfig(VideoDbInput):
    'Get video index status'
    operation: Literal["get_video_index"] = Field("get_video_index", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., min_length=1, pattern='^m-')
    index_type: Literal['spoken_word', 'scene'] = Field(..., min_length=1)
    engine: str | None = Field(None, min_length=1)


class CreateVideoIndexConfig(VideoDbInput):
    'Create video index'
    operation: Literal["create_video_index"] = Field("create_video_index", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., min_length=1, pattern='^m-')
    index_type: Literal['spoken_word', 'scene'] | None = Field(None, min_length=1)
    engine: str | None = Field(None, min_length=1)
    force: bool | None = Field(None)
    language_code: str | None = Field(None, min_length=1)
    segmentation_type: str | None = Field(None, min_length=1)
    callback_url: str | None = Field(None, min_length=1, description='Optional provider callback URL for asynchronous processing.')


class SearchVideoConfig(VideoDbInput):
    'Search within video'
    operation: Literal["search_video"] = Field("search_video", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., min_length=1, pattern='^m-')
    query: str = Field(..., min_length=1)
    index_type: Literal['spoken_word', 'scene'] | None = Field(None, min_length=1)
    search_type: Literal['semantic', 'keyword'] | None = Field(None, min_length=1)
    score_threshold: float | None = Field(None)
    result_threshold: int | None = Field(None, ge=1)
    stitch: bool | None = Field(None)
    scene_index_id: str | None = Field(None, min_length=1)
    filter: list[dict[str, Any]] | None = Field(None)


class GetVideoScenesConfig(VideoDbInput):
    'Get video scenes'
    operation: Literal["get_video_scenes"] = Field("get_video_scenes", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., min_length=1, pattern='^m-')


class CreateVideoScenesConfig(VideoDbInput):
    'Create video scenes'
    operation: Literal["create_video_scenes"] = Field("create_video_scenes", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., min_length=1, pattern='^m-')
    scene_type: Literal['shot', 'time_based'] | None = Field(None, min_length=1)
    callback_url: str | None = Field(None, min_length=1, description='Optional provider callback URL for asynchronous processing.')


class GenerateVideoClipConfig(VideoDbInput):
    'Generate video clip'
    operation: Literal["generate_video_clip"] = Field("generate_video_clip", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., min_length=1, pattern='^m-')
    prompt: str = Field(..., min_length=1)
    content_type: str | None = Field(None, min_length=1)
    model_name: str | None = Field(None, min_length=1)
    scene_index_id: str | None = Field(None, min_length=1)
    callback_url: str | None = Field(None, min_length=1, description='Optional provider callback URL for asynchronous processing.')


class ListAudiosConfig(VideoDbInput):
    'List audios'
    operation: Literal["list_audios"] = Field("list_audios", json_schema_extra={"ui:hidden": True})
    collection_id: str | None = Field(None, min_length=1)


class ListImagesConfig(VideoDbInput):
    'List images'
    operation: Literal["list_images"] = Field("list_images", json_schema_extra={"ui:hidden": True})
    collection_id: str | None = Field(None, min_length=1)


class GetAsyncResultConfig(VideoDbInput):
    'Get async operation result'
    operation: Literal["get_async_result"] = Field("get_async_result", json_schema_extra={"ui:hidden": True})
    response_id: str = Field(..., min_length=1)

# VideoDB's own MCP server: agents get its tools through a person's VideoDB sign-in.
VideoDbMcpCredential = mcp_credential("video_db", "https://mcp.videodb.io/mcp", app="VideoDB")
VideoDbCredential = Union[VideoDbAPIKeyCredential, VideoDbMcpCredential]


VideoDbConfig = Annotated[Union[GetAccountConfig, ListCollectionsConfig, CreateCollectionConfig, GetCollectionConfig, UpdateCollectionConfig, DeleteCollectionConfig, UploadMediaConfig, SearchCollectionConfig, ListVideosConfig, GetVideoConfig, UpdateVideoConfig, DeleteVideoConfig, CreateVideoStreamConfig, GetVideoTranscriptionConfig, GenerateVideoTranscriptionConfig, GetVideoIndexConfig, CreateVideoIndexConfig, SearchVideoConfig, GetVideoScenesConfig, CreateVideoScenesConfig, GenerateVideoClipConfig, ListAudiosConfig, ListImagesConfig, GetAsyncResultConfig], Field(discriminator="operation")]


class VideoDbFullConfig(NodeConfig[VideoDbConfig, VideoDbCredential]):
    pass


ROUTES = {'get_account': ('GET', '/user', [], []), 'list_collections': ('GET', '/collection', [], []), 'create_collection': ('POST', '/collection', [], []), 'get_collection': ('GET', '/collection/{collection_id}', ['collection_id'], []), 'update_collection': ('PATCH', '/collection/{collection_id}', ['collection_id'], []), 'delete_collection': ('DELETE', '/collection/{collection_id}', ['collection_id'], []), 'upload_media': ('POST', '/collection/{collection_id}/upload', ['collection_id'], []), 'search_collection': ('POST', '/collection/{collection_id}/search/', ['collection_id'], []), 'list_videos': ('GET', '/video/', [], ['collection_id', 'page_index', 'count']), 'get_video': ('GET', '/video/{video_id}', ['video_id'], ['collection_id']), 'update_video': ('PATCH', '/video/{video_id}', ['video_id'], []), 'delete_video': ('DELETE', '/video/{video_id}', ['video_id'], []), 'create_video_stream': ('POST', '/video/{video_id}/stream/', ['video_id'], []), 'get_video_transcription': ('GET', '/video/{video_id}/transcription/', ['video_id'], ['engine', 'start', 'end', 'segmenter', 'length']), 'generate_video_transcription': ('POST', '/video/{video_id}/transcription/', ['video_id'], []), 'get_video_index': ('GET', '/video/{video_id}/index/', ['video_id'], ['index_type', 'engine']), 'create_video_index': ('POST', '/video/{video_id}/index/', ['video_id'], []), 'search_video': ('POST', '/video/{video_id}/search/', ['video_id'], []), 'get_video_scenes': ('GET', '/video/{video_id}/scenes/', ['video_id'], []), 'create_video_scenes': ('POST', '/video/{video_id}/scenes/', ['video_id'], []), 'generate_video_clip': ('POST', '/video/{video_id}/clip', ['video_id'], []), 'list_audios': ('GET', '/audio/', [], ['collection_id']), 'list_images': ('GET', '/image/', [], ['collection_id']), 'get_async_result': ('GET', '/async-response/{response_id}', ['response_id'], [])}


class VideoDbNode(WorkflowNode):
    integration_type = "automation-video-db"
    credential_provider_labels = {"video_db": "VideoDB Account"}
    connection_evidence = ConnectionEvidence(noun="VideoDB account", identity_operation="get_account",
        identity_keys=("user_name", "user_email", "user_id"))

    @classmethod
    def get_config_model(cls):
        return VideoDbFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a VideoDB API key")
        key = self.config.credentials.api_key
        op = self.config.config
        method, path, path_fields, query_fields = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for field in path_fields:
            path = path.replace("{" + field + "}", quote(values.pop(field), safe=""))
        params = {field: values.pop(field) for field in query_fields if field in values}
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.videodb.io" + path,
                headers={"x-access-token": key, "Accept": "application/json"},
                params=params, **({"json": values} if method in {"POST", "PATCH"} else {}))
        if len(response.content) > 20_000_000:
            raise ValueError("VideoDB response exceeds the content limit")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("VideoDB returned a non-JSON response") from None
        def redact(value):
            if isinstance(value, str):
                return value.replace(key, "[redacted]")
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {str(k).replace(key, "[redacted]"): redact(v) for k, v in value.items()}
            return value
        body = redact(body)
        if not isinstance(body, dict):
            raise ValueError("VideoDB returned an unexpected JSON envelope")
        failed = response.status_code != 200 or body.get("success") is False or bool(body.get("error")) or body.get("status") == "failed"
        if op.operation == "get_account" and not failed:
            account = body.get("data")
            if not isinstance(account, dict) or not isinstance(account.get("user_id"), str) or not account["user_id"]:
                raise ValueError("VideoDB account response is missing its user ID")
        output = {"status": "error" if failed else "success", "http_status": response.status_code,
                  "data": body, **({"error": body} if failed else {})}
        await self.emit(output)
        return output
