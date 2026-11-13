"""JSON2Video v2: one API request per action, plus date-filtered movie polling.

Contract: https://json2video.com/docs/v2/openapi.json (2.0.0).
Auth: https://json2video.com/docs/v2/getting-started/quickstart.
Polling and movie fields: https://json2video.com/docs/v2/reference/api-endpoints/movies-status.
Webhooks are per-render destinations, not removable API subscriptions:
https://json2video.com/docs/v2/reference/webhooks.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://api.json2video.com/v2"


class JSON2VideoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="JSON2Video API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://json2video.com/dashboard/",
        "x-credential-instructions": "Copy an API key from Dashboard → API Keys. NoClick sends it in the x-api-key header. The key needs access to templates for the connection check and to the resources your workflow uses.",
    })
    credential_type: Literal["json2video_api_key"] = Field("json2video_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


# JSON2Video's own MCP server: agents get its tools through a person's JSON2Video sign-in.
Json2videoMcpCredential = mcp_credential("json2video", "https://mcp.json2video.com/mcp", app="JSON2Video")
JSON2VideoCredential = Union[JSON2VideoAPIKeyCredential, Json2videoMcpCredential]


def op(name, title, **extra):
    return Field(name, title=title, json_schema_extra={"ui:hidden": True, **extra})


def json_field(title, *, required=False, description="JSON object"):
    return Field(... if required else None, title=title, description=description,
                 json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


def object_json(value, title):
    try:
        result = json.loads(value)
    except (TypeError, ValueError):
        raise ValueError(f"{title} must be valid JSON") from None
    if not isinstance(result, dict):
        raise ValueError(f"{title} must be a JSON object")
    return result


class Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class CreateMovie(Input):
    operation: Literal["create_movie"] = op("create_movie", "Create Movie")
    movie_json: str = json_field("Movie JSON", required=True, description="Movie object with scenes/elements or a saved template and variables. Submits an asynchronous render; each call creates a project and may use credits.")


class MovieID(Input):
    project: str = Field(..., title="Project ID", min_length=16, max_length=16,
                         description="16-character project returned by Create Movie.")


class GetMovie(MovieID):
    operation: Literal["get_movie"] = op("get_movie", "Get Movie Status")
    format: Literal["simple"] | None = Field(None, title="Response Format")


class DeleteMovie(MovieID):
    operation: Literal["delete_movie"] = op("delete_movie", "Delete Rendered Movie", **{"x-method-kind": "delete"})


class MovieRange(Input):
    from_date: datetime | None = Field(None, title="From", description="ISO 8601 date/time. Maximum range is three months. Defaults to the current month.")
    to_date: datetime | None = Field(None, title="To", description="ISO 8601 date/time; defaults to the end of today.")
    limit: int = Field(100, ge=1, le=100, title="Page Size")
    next_token: str | None = Field(None, title="Next Page Token")
    format: Literal["simple"] | None = Field(None, title="Response Format")


class ListMovies(MovieRange):
    operation: Literal["list_movies"] = op("list_movies", "List Movies")


class ListTemplates(Input):
    operation: Literal["list_templates"] = op("list_templates", "List Templates")
    tag: str | None = Field(None, title="Tag")
    format: Literal["make", "jsonschema", "summary"] | None = None


class TemplateID(Input):
    id: str = Field(..., title="Template ID", min_length=1, description="Template's generated ID, not its display name.")


class GetTemplate(TemplateID):
    operation: Literal["get_template"] = op("get_template", "Get Template")
    scopes: str = Field("movie", title="Template Sections", description="Comma-separated sections, for example movie,prompt.")
    format: Literal["make", "jsonschema", "summary"] | None = None


class TemplateBody(Input):
    name: str = Field(..., title="Template Name", min_length=1, max_length=100)
    movie_json: str = json_field("Movie JSON", required=True)
    tags: str | None = Field(None, title="Tags", description="Comma-separated tags.")
    prompt: str | None = Field(None, title="AI Prompt")


class CreateTemplate(TemplateBody):
    operation: Literal["create_template"] = op("create_template", "Create Template")


class UpdateTemplate(TemplateID, TemplateBody):
    operation: Literal["update_template"] = op("update_template", "Update Template")


class DuplicateTemplate(TemplateID):
    operation: Literal["duplicate_template"] = op("duplicate_template", "Duplicate Template")
    name: str | None = Field(None, title="New Name", max_length=100)
    variables_json: str | None = json_field("Variables JSON", description="Variables merged into the source template.")


class DeleteTemplate(TemplateID):
    operation: Literal["delete_template"] = op("delete_template", "Delete Template")


class ListLibraryTemplates(Input):
    operation: Literal["list_library_templates"] = op("list_library_templates", "List Library Templates")
    tags: str | None = Field(None, title="Tags", description="Comma-separated library tags.")


class GetStorage(Input):
    operation: Literal["get_storage"] = op("get_storage", "Get Media Storage Usage")


class GetMediaFile(Input):
    operation: Literal["get_media_file"] = op("get_media_file", "Get Media File")
    path: str = Field(..., min_length=1, title="File Path")


class RequestUpload(Input):
    operation: Literal["request_upload"] = op("request_upload", "Request Media Upload URL")
    name: str = Field(..., min_length=1, title="File Name")
    content_type: str = Field(..., title="Content Type", description="MIME type, for example image/png.")
    size: int = Field(..., ge=1, le=524288000, title="File Size in Bytes")
    folder: str | None = Field(None, title="Folder", description="Use temp for non-billable temporary uploads. Upload the bytes separately with PUT to the returned uploadUrl.")


class MoveMediaFile(Input):
    operation: Literal["move_media_file"] = op("move_media_file", "Move Media File")
    name: str = Field(..., min_length=1, title="File Name")
    folder: str | None = Field(None, title="Source Folder")
    destination: str = Field(..., title="Destination Folder", description="Use / for the root folder.")


class DeleteMediaFile(Input):
    operation: Literal["delete_media_file"] = op("delete_media_file", "Delete Media File")
    name: str = Field(..., min_length=1, title="File Name")
    folder: str | None = Field(None, title="Folder")


class ListMediaFolder(Input):
    operation: Literal["list_media_folder"] = op("list_media_folder", "List Media Folder")
    path: str = Field("/", title="Folder Path")
    tree: Literal["true", "false"] | None = Field(None, title="Return Folder Tree")
    type: Literal["image", "video", "audio", "other"] | None = Field(None, title="Media Type")
    q: str | None = Field(None, title="File Name Search")
    page: int = Field(0, ge=0, title="Page", description="Zero-based page index.")
    page_size: int = Field(20, ge=1, title="Page Size")


class Folder(Input):
    folder: str = Field(..., min_length=1, title="Folder Path")


class CreateMediaFolder(Folder):
    operation: Literal["create_media_folder"] = op("create_media_folder", "Create Media Folder")


class DeleteMediaFolder(Folder):
    operation: Literal["delete_media_folder"] = op("delete_media_folder", "Delete Empty Media Folder")


class RenderSubtitles(Input):
    operation: Literal["render_subtitles"] = op("render_subtitles", "Convert SRT to ASS Subtitles")
    srt: str = Field(..., min_length=1, title="SRT Text", description="Inline timed SRT text, not a URL.", json_schema_extra={"ui:widget": "textarea"})
    resolution: Literal["sd", "hd", "full-hd", "squared", "instagram-story", "instagram-feed", "twitter-landscape", "twitter-portrait", "4k", "custom"] = "full-hd"
    width: int | None = Field(None, ge=16, le=8192)
    height: int | None = Field(None, ge=16, le=8192)
    subtitles_json: str | None = json_field("Subtitle Styling JSON", description="Object containing settings, for example {\"settings\": {\"style\": \"classic\"}}. No transcription or translation is performed.")


class OnNewMovie(PollTriggerConfigBase):
    operation: Literal["on_new_movie"] = op("on_new_movie", "On New Movie", **{"x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Movie"})
    lookback_days: int = Field(7, ge=1, le=90, title="Lookback Days", description="Poll movies created in this many days. The first poll records a baseline. Later polls emit newly matching projects.")


class OnMovieFinished(OnNewMovie):
    operation: Literal["on_movie_finished"] = op("on_movie_finished", "On Movie Render Finished", **{"x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Movie Render Finished"})


Operation = Annotated[Union[CreateMovie, GetMovie, ListMovies, DeleteMovie, ListTemplates, GetTemplate,
    CreateTemplate, UpdateTemplate, DuplicateTemplate, DeleteTemplate, ListLibraryTemplates, GetStorage,
    GetMediaFile, RequestUpload, MoveMediaFile, DeleteMediaFile, ListMediaFolder, CreateMediaFolder,
    DeleteMediaFolder, RenderSubtitles, OnNewMovie, OnMovieFinished], Field(discriminator="operation")]


class JSON2VideoNodeConfig(NodeConfig[Operation, JSON2VideoCredential]):
    pass


# Each action selects exactly one published operation; variants differ only in documented query parameters.
ROUTES = {
    "create_movie": ("POST", "/movies"), "get_movie": ("GET", "/movies"),
    "list_movies": ("GET", "/movies"), "delete_movie": ("DELETE", "/movies"),
    "list_templates": ("GET", "/templates"), "get_template": ("GET", "/templates"),
    "create_template": ("POST", "/templates"), "update_template": ("POST", "/templates"),
    "duplicate_template": ("POST", "/templates"), "delete_template": ("DELETE", "/templates"),
    "list_library_templates": ("GET", "/templates/library"), "get_storage": ("GET", "/media"),
    "get_media_file": ("GET", "/media/file"), "request_upload": ("POST", "/media/file"),
    "move_media_file": ("PUT", "/media/file"), "delete_media_file": ("DELETE", "/media/file"),
    "list_media_folder": ("GET", "/media/folder"), "create_media_folder": ("POST", "/media/folder"),
    "delete_media_folder": ("DELETE", "/media/folder"), "render_subtitles": ("POST", "/subtitles"),
}


class JSON2VideoNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-json2video"
    credential_provider_labels = {"json2video": "JSON2Video Account"}
    connection_evidence = ConnectionEvidence(noun="templates", operation="list_templates")
    edit_examples = ["Render a video from my template", "Get the finished video URL", "Run when a new movie is created", "Upload media to my library"]

    @classmethod
    def get_config_model(cls):
        return JSON2VideoNodeConfig

    @staticmethod
    async def _request(key, method, path, *, params=None, body=None):
        async with guarded_async_client(timeout=45, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params,
                headers={"x-api-key": key, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        try:
            result = response.json()
        except ValueError:
            raise ValueError(f"JSON2Video returned a non-JSON response (HTTP {response.status_code})") from None
        if not isinstance(result, dict):
            raise ValueError("JSON2Video returned an unexpected response")
        if response.status_code >= 300 or result.get("success") is False:
            message = str(result.get("message") or result.get("error") or "Request rejected").replace(key, "[redacted]")
            raise ValueError(f"JSON2Video HTTP {response.status_code}: {message}")
        return result

    @staticmethod
    def _wire(config):
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for field in tuple(values):
            if field.endswith("_json"):
                values[field[:-5]] = object_json(values.pop(field), field)
        for field, wire in (("from_date", "from"), ("to_date", "to"), ("content_type", "contentType")):
            if field in values:
                values[wire] = values.pop(field)
        action = config.operation
        if action == "create_movie":
            return None, values["movie"]
        if action in {"create_template", "update_template", "duplicate_template"}:
            query = {"id": values.pop("id")} if "id" in values else {}
            if action == "duplicate_template":
                query["action"] = "duplicate"
            return query or None, values
        if action == "move_media_file" and values.get("destination") == "/":
            values["destination"] = ""
        return (values or None, None) if ROUTES[action][0] == "GET" or action in {"delete_movie", "delete_template"} else (None, values)

    async def execute(self, inputs: dict[str, Any]):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a JSON2Video API key")
        config = self.config.config
        key = self.config.credentials.api_key
        if isinstance(config, OnNewMovie):
            return await self._poll_movies(key, config)
        query, body = self._wire(config)
        method, path = ROUTES[config.operation]
        data = await self._request(key, method, path, params=query, body=body)
        return {"status": "success", "operation": config.operation, "data": data}

    async def _poll_movies(self, key, config):
        now = datetime.now(timezone.utc)
        query = {"from": (now - timedelta(days=config.lookback_days)).isoformat(), "to": now.isoformat(), "format": "simple", "limit": 100}
        movies, tokens = [], set()
        for _ in range(100):
            data = await self._request(key, "GET", "/movies", params=dict(query))
            rows = data.get("movies")
            if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("project"), str) for row in rows):
                raise ValueError("JSON2Video movie list is missing project IDs")
            movies.extend(rows)
            if not data.get("has_next"):
                break
            token = data.get("next_token")
            if not isinstance(token, str) or not token or token in tokens:
                raise ValueError("JSON2Video returned a missing or repeated page token")
            tokens.add(token)
            query["next_token"] = token
        else:
            raise ValueError("More than 100 movie pages; reduce Lookback Days")
        if config.operation == "on_movie_finished":
            movies = [movie for movie in movies if movie.get("status") in {"done", "error", "timeout"}]
        fresh = await self._filter_unseen(movies, lambda movie: movie["project"])
        return {"status": "success", "operation": config.operation, "movies": fresh, "new_movie_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_movie_count")) if config.get("operation") in {"on_new_movie", "on_movie_finished"} else True

    @classmethod
    def resolve_agent_event(cls, output):
        movies = output.get("movies") if isinstance(output, dict) else None
        if not isinstance(movies, list):
            return super().resolve_agent_event(output)
        if not movies:
            return None
        lines = [f"- Project {movie['project']}: {movie.get('status') or 'submitted'}; created {movie.get('created_at') or 'recently'}; video {movie.get('url') or 'not available yet'}" for movie in movies[:10]]
        event = "movie render(s) finished" if output.get("operation") == "on_movie_finished" else "new movie(s)"
        return {"text": f"JSON2Video account: {len(movies)} {event}. Use the project IDs to get render status or manage the videos.\n" + "\n".join(lines), "conversation_key": None}
