"""Wowza Video REST API (BETA), pinned from the provider's OpenAPI document.

Every action maps to one endpoint; list actions return one caller-selected page.
The video poll reads every page in its declared creation-time scope before deduping.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.video.wowza.com/api/beta"


class WowzaAccessToken(BaseModel):
    model_config = ConfigDict(title="Wowza Access Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.wowza.com/docs/how-to-use-the-wowza-video-rest-api#authentication",
            "x-credential-instructions": "Paste your Wowza Video API access token from the Wowza Video account. NoClick sends it as a Bearer token to api.video.wowza.com. The connection check lists your live streams; allow the read and write permissions needed for your automation.",
        })
    credential_type: Literal["wowza_access_token"] = Field("wowza_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=8192, title="Access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the access token, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _List(_Input):
    page: int = Field(1, ge=1, title="Page")
    per_page: int = Field(100, ge=1, le=1000, title="Records per page")


class _Resource(_Input):
    id: str = Field(..., min_length=1, max_length=200, title="Resource ID", pattern=r"^[A-Za-z0-9_-]+$")


class _VideoScope(_List):
    created_at: str | None = Field(None, description="Only videos created after this ISO-8601 timestamp.")
    updated_at: str | None = Field(None, description="Only videos updated after this ISO-8601 timestamp.")
    state: str | None = Field(None, description="Video encoding state, such as FINISHED.")
    query: str | None = Field(None, title="Search text")
    sort_column: Literal["created_at", "name", "published_at", "duration"] | None = None
    sort_direction: Literal["asc", "desc"] | None = None
    origin_id: str | None = Field(None, title="Origin stream ID")
    categories: str | None = Field(None, description="Comma-separated category IDs (up to four).")


class WowzaListLiveStreamsConfig(_List):
    """Fetch all live streams."""
    operation: Literal["list_live_streams"] = Field("list_live_streams", json_schema_extra={"ui:hidden": True, "x-display-name": 'Fetch all live streams', "x-is-trigger": False})


class WowzaGetLiveStreamConfig(_Resource):
    """Fetch a live stream."""
    operation: Literal["get_live_stream"] = Field("get_live_stream", json_schema_extra={"ui:hidden": True, "x-display-name": 'Fetch a live stream', "x-is-trigger": False})


class WowzaCreateLiveStreamConfig(_Input):
    """Create a live stream."""
    operation: Literal["create_live_stream"] = Field("create_live_stream", json_schema_extra={"ui:hidden": True, "x-display-name": 'Create a live stream', "x-is-trigger": False})
    name: str = Field(..., min_length=1, max_length=200)
    broadcast_location: Literal['asia_pacific_australia', 'asia_pacific_india', 'asia_pacific_japan', 'asia_pacific_singapore', 'asia_pacific_s_korea', 'asia_pacific_taiwan', 'eu_belgium', 'eu_germany', 'eu_ireland', 'south_america_brazil', 'us_central_iowa', 'us_east_s_carolina', 'us_east_virginia', 'us_west_california', 'us_west_oregon']
    encoder: Literal['wowza_clearcaster', 'wowza_gocoder', 'wowza_streaming_engine', 'media_ds', 'axis', 'epiphan', 'file', 'hauppauge', 'jvc', 'live_u', 'matrox', 'newtek_tricaster', 'osprey', 'sony', 'telestream_wirecast', 'teradek_cube', 'vmix', 'x_split', 'ipcamera', 'other_rtmp', 'other_rtsp', 'other_webrtc', 'other_udp', 'other_srt']
    description: str | None = None
    recording: bool | None = None
    save_asset: bool | None = None


class WowzaUpdateLiveStreamConfig(_Resource):
    """Update a live stream."""
    operation: Literal["update_live_stream"] = Field("update_live_stream", json_schema_extra={"ui:hidden": True, "x-display-name": 'Update a live stream', "x-is-trigger": False})
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    recording: bool | None = None
    save_asset: bool | None = None

    @model_validator(mode="after")
    def needs_change(self):
        if not (self.model_fields_set - {"operation", "id"}):
            raise ValueError("Provide at least one field to update")
        return self


class WowzaDeleteLiveStreamConfig(_Resource):
    """Delete a live stream."""
    operation: Literal["delete_live_stream"] = Field("delete_live_stream", json_schema_extra={"ui:hidden": True, "x-display-name": 'Delete a live stream', "x-is-trigger": False})


class WowzaStartLiveStreamConfig(_Resource):
    """Start a live stream."""
    operation: Literal["start_live_stream"] = Field("start_live_stream", json_schema_extra={"ui:hidden": True, "x-display-name": 'Start a live stream', "x-is-trigger": False})


class WowzaStopLiveStreamConfig(_Resource):
    """Stop a live stream."""
    operation: Literal["stop_live_stream"] = Field("stop_live_stream", json_schema_extra={"ui:hidden": True, "x-display-name": 'Stop a live stream', "x-is-trigger": False})


class WowzaResetLiveStreamConfig(_Resource):
    """Reset a live stream."""
    operation: Literal["reset_live_stream"] = Field("reset_live_stream", json_schema_extra={"ui:hidden": True, "x-display-name": 'Reset a live stream', "x-is-trigger": False})


class WowzaGetLiveStreamStateConfig(_Resource):
    """Fetch the state of a live stream."""
    operation: Literal["get_live_stream_state"] = Field("get_live_stream_state", json_schema_extra={"ui:hidden": True, "x-display-name": 'Fetch the state of a live stream', "x-is-trigger": False})


class WowzaListTranscodersConfig(_List):
    """Fetch all transcoders."""
    operation: Literal["list_transcoders"] = Field("list_transcoders", json_schema_extra={"ui:hidden": True, "x-display-name": 'Fetch all transcoders', "x-is-trigger": False})


class WowzaGetTranscoderConfig(_Resource):
    """Fetch a transcoder."""
    operation: Literal["get_transcoder"] = Field("get_transcoder", json_schema_extra={"ui:hidden": True, "x-display-name": 'Fetch a transcoder', "x-is-trigger": False})


class WowzaStartTranscoderConfig(_Resource):
    """Start a transcoder."""
    operation: Literal["start_transcoder"] = Field("start_transcoder", json_schema_extra={"ui:hidden": True, "x-display-name": 'Start a transcoder', "x-is-trigger": False})


class WowzaStopTranscoderConfig(_Resource):
    """Stop a transcoder."""
    operation: Literal["stop_transcoder"] = Field("stop_transcoder", json_schema_extra={"ui:hidden": True, "x-display-name": 'Stop a transcoder', "x-is-trigger": False})


class WowzaStartRecordingConfig(_Resource):
    """Start recording."""
    operation: Literal["start_recording"] = Field("start_recording", json_schema_extra={"ui:hidden": True, "x-display-name": 'Start recording', "x-is-trigger": False})


class WowzaStopRecordingConfig(_Resource):
    """Stop recording."""
    operation: Literal["stop_recording"] = Field("stop_recording", json_schema_extra={"ui:hidden": True, "x-display-name": 'Stop recording', "x-is-trigger": False})


class WowzaGetTranscoderStateConfig(_Resource):
    """Fetch the state and uptime ID of a transcoder."""
    operation: Literal["get_transcoder_state"] = Field("get_transcoder_state", json_schema_extra={"ui:hidden": True, "x-display-name": 'Fetch the state and uptime ID of a transcoder', "x-is-trigger": False})


class WowzaListVideosConfig(_VideoScope):
    """Fetch all videos."""
    operation: Literal["list_videos"] = Field("list_videos", json_schema_extra={"ui:hidden": True, "x-display-name": 'Fetch all videos', "x-is-trigger": False})


class WowzaGetVideoConfig(_Resource):
    """Fetch a video."""
    operation: Literal["get_video"] = Field("get_video", json_schema_extra={"ui:hidden": True, "x-display-name": 'Fetch a video', "x-is-trigger": False})


class WowzaUpdateVideoConfig(_Resource):
    """Update a video's metadata."""
    operation: Literal["update_video"] = Field("update_video", json_schema_extra={"ui:hidden": True, "x-display-name": "Update a video's metadata", "x-is-trigger": False})
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    published: bool | None = None
    category_id: str | None = None

    @model_validator(mode="after")
    def needs_change(self):
        if not (self.model_fields_set - {"operation", "id"}):
            raise ValueError("Provide at least one field to update")
        return self


class WowzaDeleteVideoConfig(_Resource):
    """Delete a video."""
    operation: Literal["delete_video"] = Field("delete_video", json_schema_extra={"ui:hidden": True, "x-display-name": 'Delete a video', "x-is-trigger": False})


class WowzaListSchedulesConfig(_List):
    """Fetch all schedules."""
    operation: Literal["list_schedules"] = Field("list_schedules", json_schema_extra={"ui:hidden": True, "x-display-name": 'Fetch all schedules', "x-is-trigger": False})


class WowzaGetScheduleConfig(_Resource):
    """Fetch a schedule."""
    operation: Literal["get_schedule"] = Field("get_schedule", json_schema_extra={"ui:hidden": True, "x-display-name": 'Fetch a schedule', "x-is-trigger": False})


class WowzaEnableScheduleConfig(_Resource):
    """Enable a schedule."""
    operation: Literal["enable_schedule"] = Field("enable_schedule", json_schema_extra={"ui:hidden": True, "x-display-name": 'Enable a schedule', "x-is-trigger": False})


class WowzaDisableScheduleConfig(_Resource):
    """Disable a schedule."""
    operation: Literal["disable_schedule"] = Field("disable_schedule", json_schema_extra={"ui:hidden": True, "x-display-name": 'Disable a schedule', "x-is-trigger": False})


class WowzaOnNewVideoConfig(PollTriggerConfigBase):
    operation: Literal["on_new_video"] = Field("on_new_video", title="On New Video", json_schema_extra={
        "const": "on_new_video", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On New Video",
    })
    created_at: str | None = Field(None, title="Created after", description="Optional ISO-8601 lower bound. Existing videos are baselined when the trigger is armed. Monitors at most 10,000 videos; narrow this scope for larger libraries.")


WowzaOperation = Annotated[
    Union[
        WowzaListLiveStreamsConfig,
        WowzaGetLiveStreamConfig,
        WowzaCreateLiveStreamConfig,
        WowzaUpdateLiveStreamConfig,
        WowzaDeleteLiveStreamConfig,
        WowzaStartLiveStreamConfig,
        WowzaStopLiveStreamConfig,
        WowzaResetLiveStreamConfig,
        WowzaGetLiveStreamStateConfig,
        WowzaListTranscodersConfig,
        WowzaGetTranscoderConfig,
        WowzaStartTranscoderConfig,
        WowzaStopTranscoderConfig,
        WowzaStartRecordingConfig,
        WowzaStopRecordingConfig,
        WowzaGetTranscoderStateConfig,
        WowzaListVideosConfig,
        WowzaGetVideoConfig,
        WowzaUpdateVideoConfig,
        WowzaDeleteVideoConfig,
        WowzaListSchedulesConfig,
        WowzaGetScheduleConfig,
        WowzaEnableScheduleConfig,
        WowzaDisableScheduleConfig,
        WowzaOnNewVideoConfig,
    ],
    Field(discriminator="operation"),
]


class WowzaNodeConfig(NodeConfig[WowzaOperation, WowzaAccessToken]):
    pass


ROUTES = {'list_live_streams': ('GET', '/live_streams', ['page', 'per_page'], None),
 'get_live_stream': ('GET', '/live_streams/{id}', [], None),
 'create_live_stream': ('POST', '/live_streams', [], 'live_stream'),
 'update_live_stream': ('PATCH', '/live_streams/{id}', [], 'live_stream'),
 'delete_live_stream': ('DELETE', '/live_streams/{id}', [], None),
 'start_live_stream': ('PUT', '/live_streams/{id}/start', [], None),
 'stop_live_stream': ('PUT', '/live_streams/{id}/stop', [], None),
 'reset_live_stream': ('PUT', '/live_streams/{id}/reset', [], None),
 'get_live_stream_state': ('GET', '/live_streams/{id}/state', [], None),
 'list_transcoders': ('GET', '/transcoders', ['page', 'per_page'], None),
 'get_transcoder': ('GET', '/transcoders/{id}', [], None),
 'start_transcoder': ('PUT', '/transcoders/{id}/start', [], None),
 'stop_transcoder': ('PUT', '/transcoders/{id}/stop', [], None),
 'start_recording': ('PUT', '/transcoders/{id}/start_recording', [], None),
 'stop_recording': ('PUT', '/transcoders/{id}/stop_recording', [], None),
 'get_transcoder_state': ('GET', '/transcoders/{id}/state', [], None),
 'list_videos': ('GET',
                 '/videos',
                 ['page',
                  'per_page',
                  'created_at',
                  'updated_at',
                  'state',
                  'query',
                  'sort_column',
                  'sort_direction',
                  'origin_id',
                  'categories'],
                 None),
 'get_video': ('GET', '/videos/{id}', [], None),
 'update_video': ('PATCH', '/videos/{id}', [], 'video'),
 'delete_video': ('DELETE', '/videos/{id}', [], None),
 'list_schedules': ('GET', '/schedules', ['page', 'per_page'], None),
 'get_schedule': ('GET', '/schedules/{id}', [], None),
 'enable_schedule': ('PUT', '/schedules/{id}/enable', [], None),
 'disable_schedule': ('PUT', '/schedules/{id}/disable', [], None)}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        for key in list(value):
            if key.lower() in {"authorization", "access_token"}:
                del value[key]
            else:
                value[key] = _redact(value[key], token)
        return value
    return value


class WowzaNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-wowza"
    connection_evidence = ConnectionEvidence(noun="live streams", operation="list_live_streams")

    @classmethod
    def get_config_model(cls):
        return WowzaNodeConfig

    @staticmethod
    async def _request(token, method, path, *, query=None, body=None):
        try:
            async with guarded_async_client(timeout=45, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    params=query, **({"json": body} if body is not None else {}))
        except (httpx.TimeoutException, httpx.TransportError):
            raise ValueError("Wowza request did not complete; inspect the account before retrying a write") from None
        if not 200 <= response.status_code < 300:
            message = "Wowza HTTP " + str(response.status_code)
            try:
                error = response.json()
                meta = error.get("meta") if isinstance(error, dict) else None
                if isinstance(meta, dict):
                    message += ": " + str(meta.get("message") or meta.get("title") or "Request rejected")[:1000]
            except ValueError:
                pass
            raise ValueError(_redact(message, token))
        if response.status_code == 204:
            return {"success": True}
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Wowza returned invalid JSON") from None
        if not isinstance(data, dict):
            raise ValueError("Wowza returned an unexpected response")
        return _redact(data, token)

    async def _poll_videos(self, token, op):
        videos = []
        for page in range(1, 11):
            query = {"page": page, "per_page": 1000, "sort_column": "created_at", "sort_direction": "asc"}
            if op.created_at:
                query["created_at"] = op.created_at
            result = await self._request(token, "GET", "/videos", query=query)
            rows = result.get("videos")
            if not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get("id") for row in rows):
                raise ValueError("Wowza returned videos without usable IDs")
            videos.extend(rows)
            pagination = result.get("pagination")
            if not isinstance(pagination, dict) or not isinstance(pagination.get("total_pages"), int):
                raise ValueError("Wowza returned no video pagination metadata")
            if page >= pagination["total_pages"]:
                break
        else:
            raise ValueError("Wowza video library exceeds 10,000 videos; set Created after to narrow the trigger")
        fresh = await self._filter_unseen(videos, lambda video: str(video["id"]))
        return {"videos": fresh, "new_video_count": len(fresh)}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Wowza access token")
        op = self.config.config
        token = self.config.credentials.access_token
        if isinstance(op, WowzaOnNewVideoConfig):
            return await self._poll_videos(token, op)
        method, path, query_fields, wrapper = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            path = path.replace("{id}", quote(values.pop("id"), safe=""))
        query = {key: values.pop(key) for key in query_fields if key in values}
        body = {wrapper: values} if wrapper else None
        return await self._request(token, method, path, query=query, body=body)

    @classmethod
    def resolve_agent_event(cls, output):
        videos = output.get("videos") if isinstance(output, dict) else None
        if not isinstance(videos, list):
            return super().resolve_agent_event(output)
        if not videos:
            return None
        lines = [f"- {video.get('name') or 'Untitled video'} (video ID: {video['id']})" for video in videos[:10]]
        if len(videos) > 10:
            lines.append(f"- and {len(videos) - 10} more")
        return {"text": f"Wowza: {len(videos)} new video(s) in your video library.\n" + "\n".join(lines), "conversation_key": None}
