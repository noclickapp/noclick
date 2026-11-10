"""PeerTube REST operations, pinned to the provider's published OpenAPI contract.

Existing bearer tokens are pasted by the account owner; they are not refreshed.
All requests stay on the chosen instance, with DNS-pinned SSRF protection.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret, https_origin
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client
from nodes.scopes.cpy import CPY_SCOPES


class PeerTubeTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="PeerTube Access Token",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.joinpeertube.org/api/rest-getting-started",
            "x-credential-instructions": "Enter your PeerTube instance URL and paste an existing access_token obtained using the official REST API instructions. Tokens expire: replace the token when it expires. NoClick does not store your password or automatically refresh tokens. Use an account allowed to manage the videos and channels you select.",
        },
    )
    credential_type: Literal["cpy_access_token"] = Field(
        "cpy_access_token", json_schema_extra={"ui:hidden": True}
    )
    instance_url: str = Field(
        ...,
        title="Instance URL",
        description="Public HTTPS origin of your PeerTube instance, for example https://peertube.example.com",
    )
    access_token: str = Field(
        ...,
        min_length=1,
        title="Access token",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("instance_url", mode="before")
    @classmethod
    def origin(cls, value):
        origin = https_origin(value, field_name="Instance URL")
        parsed = urlsplit(origin)
        if parsed.scheme != "https" or parsed.port not in (None, 443):
            raise ValueError("Use your instance's public HTTPS URL on port 443")
        return origin

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        token = clean_secret(value, field_name="Access token", key=True)
        if not token or any(c.isspace() for c in token):
            raise ValueError("Paste the access token without the Bearer prefix")
        return token


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @field_validator("video_id", mode="before", check_fields=False)
    @classmethod
    def video_reference(cls, value):
        if isinstance(value, bool) or not re.fullmatch(
            r"(?:[1-9][0-9]*|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}|[a-zA-Z0-9]{22})",
            str(value),
        ):
            raise ValueError("Use a positive video ID, UUIDv4 or short UUID")
        return int(value) if str(value).isdigit() else value


class _Page(_Input):
    start: int = Field(
        0,
        ge=0,
        title="Start offset",
        description="Zero-based offset; add the number of returned items for the next page.",
    )
    count: int = Field(15, ge=1, le=100, title="Page size")


class PeerTubeGetMyAccountConfig(_Input):
    operation: Literal["get_my_account"] = Field(
        "get_my_account",
        title="Get My Account",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Get My Account",
            "x-category": "Accounts",
            "x-is-trigger": False,
        },
    )


class PeerTubeListVideosConfig(_Page):
    operation: Literal["list_videos"] = Field(
        "list_videos",
        title="List Videos",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List Videos",
            "x-category": "Videos",
            "x-is-trigger": False,
        },
    )
    sort: Literal[
        "name",
        "-duration",
        "-createdAt",
        "-publishedAt",
        "-views",
        "-likes",
        "-comments",
        "-trending",
        "-hot",
        "-best",
    ] = Field("-createdAt", title="Sort")


class PeerTubeSearchVideosConfig(_Page):
    operation: Literal["search_videos"] = Field(
        "search_videos",
        title="Search Videos",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Search Videos",
            "x-category": "Videos",
            "x-is-trigger": False,
        },
    )
    search: str = Field(..., min_length=1, title="Search query")
    sort: Literal[
        "name",
        "-duration",
        "-createdAt",
        "-publishedAt",
        "-views",
        "-likes",
        "-comments",
        "-trending",
        "-hot",
        "-best",
    ] = Field("-createdAt", title="Sort")


class PeerTubeGetVideoConfig(_Input):
    operation: Literal["get_video"] = Field(
        "get_video",
        title="Get Video",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Get Video",
            "x-category": "Videos",
            "x-is-trigger": False,
        },
    )
    video_id: Union[int, str] = Field(..., title="Video ID or UUID")


class PeerTubeUpdateVideoConfig(_Input):
    operation: Literal["update_video"] = Field(
        "update_video",
        title="Update Video",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Update Video",
            "x-category": "Videos",
            "x-is-trigger": False,
        },
    )
    video_id: Union[int, str] = Field(..., title="Video ID or UUID")
    name: Optional[str] = Field(None, min_length=3, max_length=120, title="Video title")
    description: Optional[str] = Field(None, title="Description")
    privacy: Optional[Literal[1, 2, 3, 4, 5]] = Field(
        None,
        title="Privacy",
        description="1 public, 2 unlisted, 3 private, 4 internal, 5 password protected",
    )
    download_enabled: Optional[bool] = Field(None, title="Allow downloads")


class PeerTubeDeleteVideoConfig(_Input):
    operation: Literal["delete_video"] = Field(
        "delete_video",
        title="Delete Video",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Delete Video",
            "x-category": "Videos",
            "x-is-trigger": False,
        },
    )
    video_id: Union[int, str] = Field(..., title="Video ID or UUID")


class PeerTubeImportVideoConfig(_Input):
    operation: Literal["import_video"] = Field(
        "import_video",
        title="Import Video",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Import Video",
            "x-category": "Videos",
            "x-is-trigger": False,
        },
    )
    target_url: str = Field(
        ...,
        min_length=1,
        title="Video URL",
        description="URL to import; the instance must allow remote imports",
    )
    channel_id: int = Field(..., ge=1, title="Destination channel ID")
    name: str = Field(..., min_length=3, max_length=120, title="Video title")


class PeerTubeListChannelsConfig(_Page):
    operation: Literal["list_channels"] = Field(
        "list_channels",
        title="List Channels",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List Channels",
            "x-category": "Channels",
            "x-is-trigger": False,
        },
    )
    sort: Literal["-createdAt", "createdAt", "name", "-name"] = Field(
        "-createdAt", title="Sort"
    )


class PeerTubeGetChannelConfig(_Input):
    operation: Literal["get_channel"] = Field(
        "get_channel",
        title="Get Channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Get Channel",
            "x-category": "Channels",
            "x-is-trigger": False,
        },
    )
    channel_handle: str = Field(
        ...,
        min_length=1,
        title="Channel handle",
        description="Local channel name or name@instance handle",
    )


class PeerTubeCreateChannelConfig(_Input):
    operation: Literal["create_channel"] = Field(
        "create_channel",
        title="Create Channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Create Channel",
            "x-category": "Channels",
            "x-is-trigger": False,
        },
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_.:\-]+$",
        title="Channel username",
    )
    display_name: str = Field(..., min_length=1, title="Display name")
    description: Optional[str] = Field(None, title="Description")
    support: Optional[str] = Field(None, title="Support text")


class PeerTubeUpdateChannelConfig(_Input):
    operation: Literal["update_channel"] = Field(
        "update_channel",
        title="Update Channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Update Channel",
            "x-category": "Channels",
            "x-is-trigger": False,
        },
    )
    channel_handle: str = Field(
        ...,
        min_length=1,
        title="Channel handle",
        description="Local channel name or name@instance handle",
    )
    display_name: Optional[str] = Field(None, min_length=1, title="Display name")
    description: Optional[str] = Field(None, title="Description")
    support: Optional[str] = Field(None, title="Support text")


class PeerTubeDeleteChannelConfig(_Input):
    operation: Literal["delete_channel"] = Field(
        "delete_channel",
        title="Delete Channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Delete Channel",
            "x-category": "Channels",
            "x-is-trigger": False,
        },
    )
    channel_handle: str = Field(
        ...,
        min_length=1,
        title="Channel handle",
        description="Local channel name or name@instance handle",
    )


class PeerTubeListChannelVideosConfig(_Page):
    operation: Literal["list_channel_videos"] = Field(
        "list_channel_videos",
        title="List Channel Videos",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List Channel Videos",
            "x-category": "Videos",
            "x-is-trigger": False,
        },
    )
    channel_handle: str = Field(
        ...,
        min_length=1,
        title="Channel handle",
        description="Local channel name or name@instance handle",
    )
    sort: Literal[
        "name",
        "-duration",
        "-createdAt",
        "-publishedAt",
        "-views",
        "-likes",
        "-comments",
        "-trending",
        "-hot",
        "-best",
    ] = Field("-createdAt", title="Sort")


class PeerTubeGetAccountConfig(_Input):
    operation: Literal["get_account"] = Field(
        "get_account",
        title="Get Account",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Get Account",
            "x-category": "Accounts",
            "x-is-trigger": False,
        },
    )
    account_name: str = Field(..., min_length=1, title="Account handle")


class PeerTubeListAccountVideosConfig(_Page):
    operation: Literal["list_account_videos"] = Field(
        "list_account_videos",
        title="List Account Videos",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List Account Videos",
            "x-category": "Videos",
            "x-is-trigger": False,
        },
    )
    account_name: str = Field(..., min_length=1, title="Account handle")
    sort: Literal[
        "name",
        "-duration",
        "-createdAt",
        "-publishedAt",
        "-views",
        "-likes",
        "-comments",
        "-trending",
        "-hot",
        "-best",
    ] = Field("-createdAt", title="Sort")


class PeerTubeListPlaylistsConfig(_Page):
    operation: Literal["list_playlists"] = Field(
        "list_playlists",
        title="List Playlists",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List Playlists",
            "x-category": "Playlists",
            "x-is-trigger": False,
        },
    )
    sort: Literal["-createdAt", "createdAt"] = Field("-createdAt", title="Sort")


class PeerTubeCreatePlaylistConfig(_Input):
    operation: Literal["create_playlist"] = Field(
        "create_playlist",
        title="Create Playlist",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Create Playlist",
            "x-category": "Playlists",
            "x-is-trigger": False,
        },
    )
    display_name: str = Field(..., min_length=1, max_length=120, title="Display name")
    description: Optional[str] = Field(
        None, min_length=3, max_length=1000, title="Description"
    )
    privacy: Optional[Literal[1, 2, 3]] = Field(
        None, title="Privacy", description="1 public, 2 unlisted, 3 private"
    )
    channel_id: Optional[int] = Field(None, ge=1, title="Channel ID")


class PeerTubeListPlaylistVideosConfig(_Page):
    operation: Literal["list_playlist_videos"] = Field(
        "list_playlist_videos",
        title="List Playlist Videos",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List Playlist Videos",
            "x-category": "Videos",
            "x-is-trigger": False,
        },
    )
    playlist_id: int = Field(..., ge=1, title="Playlist ID")


class PeerTubeAddPlaylistVideoConfig(_Input):
    operation: Literal["add_playlist_video"] = Field(
        "add_playlist_video",
        title="Add Playlist Video",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Add Playlist Video",
            "x-category": "Videos",
            "x-is-trigger": False,
        },
    )
    playlist_id: int = Field(..., ge=1, title="Playlist ID")
    video_id: Union[int, str] = Field(..., title="Video ID or UUID")
    start_timestamp: Optional[int] = Field(None, ge=0, title="Start at (seconds)")
    stop_timestamp: Optional[int] = Field(None, ge=0, title="Stop at (seconds)")


class PeerTubeRemovePlaylistVideoConfig(_Input):
    operation: Literal["remove_playlist_video"] = Field(
        "remove_playlist_video",
        title="Remove Playlist Video",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Remove Playlist Video",
            "x-category": "Videos",
            "x-is-trigger": False,
        },
    )
    playlist_id: int = Field(..., ge=1, title="Playlist ID")
    element_id: int = Field(..., ge=1, title="Playlist element ID")


class PeerTubeListCaptionsConfig(_Input):
    operation: Literal["list_captions"] = Field(
        "list_captions",
        title="List Captions",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List Captions",
            "x-category": "Videos",
            "x-is-trigger": False,
        },
    )
    video_id: Union[int, str] = Field(..., title="Video ID or UUID")


class PeerTubeGetChaptersConfig(_Input):
    operation: Literal["get_chapters"] = Field(
        "get_chapters",
        title="Get Chapters",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Get Chapters",
            "x-category": "Videos",
            "x-is-trigger": False,
        },
    )
    video_id: Union[int, str] = Field(..., title="Video ID or UUID")


class PeerTubeOnNewChannelVideoConfig(PollTriggerConfigBase):
    operation: Literal["on_new_channel_video"] = Field(
        "on_new_channel_video",
        title="On New Video",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "On New Channel Video",
            "x-category": "Triggers",
            "x-is-trigger": True,
        },
    )
    channel_handle: str = Field(
        ...,
        min_length=1,
        title="Channel handle",
        description="Local channel name or name@instance handle",
    )


class PeerTubeOnNewChannelConfig(PollTriggerConfigBase):
    operation: Literal["on_new_channel"] = Field(
        "on_new_channel",
        title="On New Channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "On New Channel",
            "x-category": "Triggers",
            "x-is-trigger": True,
        },
    )


PeerTubeOperation = Annotated[
    Union[
        PeerTubeGetMyAccountConfig,
        PeerTubeListVideosConfig,
        PeerTubeSearchVideosConfig,
        PeerTubeGetVideoConfig,
        PeerTubeUpdateVideoConfig,
        PeerTubeDeleteVideoConfig,
        PeerTubeImportVideoConfig,
        PeerTubeListChannelsConfig,
        PeerTubeGetChannelConfig,
        PeerTubeCreateChannelConfig,
        PeerTubeUpdateChannelConfig,
        PeerTubeDeleteChannelConfig,
        PeerTubeListChannelVideosConfig,
        PeerTubeGetAccountConfig,
        PeerTubeListAccountVideosConfig,
        PeerTubeListPlaylistsConfig,
        PeerTubeCreatePlaylistConfig,
        PeerTubeListPlaylistVideosConfig,
        PeerTubeAddPlaylistVideoConfig,
        PeerTubeRemovePlaylistVideoConfig,
        PeerTubeListCaptionsConfig,
        PeerTubeGetChaptersConfig,
        PeerTubeOnNewChannelVideoConfig,
        PeerTubeOnNewChannelConfig,
    ],
    Field(discriminator="operation"),
]


class PeerTubeConfig(NodeConfig[PeerTubeOperation, PeerTubeTokenCredential]):
    pass


OPERATIONS = {
    "get_my_account": {
        "method": "GET",
        "path": "/api/v1/users/me",
        "query": (),
        "body": {},
        "encoding": "json",
    },
    "list_videos": {
        "method": "GET",
        "path": "/api/v1/videos",
        "query": ("start", "count", "sort"),
        "body": {},
        "encoding": "json",
    },
    "search_videos": {
        "method": "GET",
        "path": "/api/v1/search/videos",
        "query": ("search", "start", "count", "sort"),
        "body": {},
        "encoding": "json",
    },
    "get_video": {
        "method": "GET",
        "path": "/api/v1/videos/{video_id}",
        "query": (),
        "body": {},
        "encoding": "json",
    },
    "update_video": {
        "method": "PUT",
        "path": "/api/v1/videos/{video_id}",
        "query": (),
        "body": {
            "name": "name",
            "description": "description",
            "privacy": "privacy",
            "download_enabled": "downloadEnabled",
        },
        "encoding": "multipart",
    },
    "delete_video": {
        "method": "DELETE",
        "path": "/api/v1/videos/{video_id}",
        "query": (),
        "body": {},
        "encoding": "json",
    },
    "import_video": {
        "method": "POST",
        "path": "/api/v1/videos/imports",
        "query": (),
        "body": {"target_url": "targetUrl", "channel_id": "channelId", "name": "name"},
        "encoding": "multipart",
    },
    "list_channels": {
        "method": "GET",
        "path": "/api/v1/video-channels",
        "query": ("start", "count", "sort"),
        "body": {},
        "encoding": "json",
    },
    "get_channel": {
        "method": "GET",
        "path": "/api/v1/video-channels/{channel_handle}",
        "query": (),
        "body": {},
        "encoding": "json",
    },
    "create_channel": {
        "method": "POST",
        "path": "/api/v1/video-channels",
        "query": (),
        "body": {
            "name": "name",
            "display_name": "displayName",
            "description": "description",
            "support": "support",
        },
        "encoding": "json",
    },
    "update_channel": {
        "method": "PUT",
        "path": "/api/v1/video-channels/{channel_handle}",
        "query": (),
        "body": {
            "display_name": "displayName",
            "description": "description",
            "support": "support",
        },
        "encoding": "json",
    },
    "delete_channel": {
        "method": "DELETE",
        "path": "/api/v1/video-channels/{channel_handle}",
        "query": (),
        "body": {},
        "encoding": "json",
    },
    "list_channel_videos": {
        "method": "GET",
        "path": "/api/v1/video-channels/{channel_handle}/videos",
        "query": ("start", "count", "sort"),
        "body": {},
        "encoding": "json",
    },
    "get_account": {
        "method": "GET",
        "path": "/api/v1/accounts/{account_name}",
        "query": (),
        "body": {},
        "encoding": "json",
    },
    "list_account_videos": {
        "method": "GET",
        "path": "/api/v1/accounts/{account_name}/videos",
        "query": ("start", "count", "sort"),
        "body": {},
        "encoding": "json",
    },
    "list_playlists": {
        "method": "GET",
        "path": "/api/v1/video-playlists",
        "query": ("start", "count", "sort"),
        "body": {},
        "encoding": "json",
    },
    "create_playlist": {
        "method": "POST",
        "path": "/api/v1/video-playlists",
        "query": (),
        "body": {
            "display_name": "displayName",
            "description": "description",
            "privacy": "privacy",
            "channel_id": "videoChannelId",
        },
        "encoding": "multipart",
    },
    "list_playlist_videos": {
        "method": "GET",
        "path": "/api/v1/video-playlists/{playlist_id}/videos",
        "query": ("start", "count"),
        "body": {},
        "encoding": "json",
    },
    "add_playlist_video": {
        "method": "POST",
        "path": "/api/v1/video-playlists/{playlist_id}/videos",
        "query": (),
        "body": {
            "video_id": "videoId",
            "start_timestamp": "startTimestamp",
            "stop_timestamp": "stopTimestamp",
        },
        "encoding": "json",
    },
    "remove_playlist_video": {
        "method": "DELETE",
        "path": "/api/v1/video-playlists/{playlist_id}/videos/{element_id}",
        "query": (),
        "body": {},
        "encoding": "json",
    },
    "list_captions": {
        "method": "GET",
        "path": "/api/v1/videos/{video_id}/captions",
        "query": (),
        "body": {},
        "encoding": "json",
    },
    "get_chapters": {
        "method": "GET",
        "path": "/api/v1/videos/{video_id}/chapters",
        "query": (),
        "body": {},
        "encoding": "json",
    },
}


class PeerTubeNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-cpy"
    credential_provider_labels = {"cpy": "PeerTube"}
    scope_registry = CPY_SCOPES
    connection_evidence = ConnectionEvidence(
        identity_operation="get_my_account",
        noun="PeerTube account",
        identity_keys=("username", "email"),
    )
    edit_examples = [
        "Import a video into my PeerTube channel",
        "Add a video to a playlist",
        "Watch for new videos on a PeerTube channel",
    ]

    @classmethod
    def get_config_model(cls):
        return PeerTubeConfig

    @staticmethod
    async def _request(
        credential, method, path, *, params=None, body=None, encoding="json"
    ):
        kwargs = {
            "params": params,
            "headers": {
                "Authorization": "Bearer " + credential.access_token,
                "Accept": "application/json",
            },
        }
        if body:
            if encoding == "multipart":
                kwargs["files"] = {
                    key: (
                        None,
                        str(value).lower() if isinstance(value, bool) else str(value),
                    )
                    for key, value in body.items()
                }
            else:
                kwargs["json"] = body
        try:
            async with guarded_async_client(
                timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method, credential.instance_url + path, **kwargs
                )
        except httpx.RequestError:
            raise ValueError("PeerTube instance could not be reached") from None
        if not 200 <= response.status_code < 300:
            text = response.text.replace(credential.access_token, "[redacted]")[:500]
            raise ValueError(f"PeerTube HTTP {response.status_code}: {text}")
        if response.status_code == 204 or not response.content:
            return {"success": True}
        try:
            result = response.json()
        except ValueError:
            raise ValueError(
                "PeerTube returned a non-JSON response; check the instance URL"
            ) from None
        if not isinstance(result, (dict, list)):
            raise ValueError("PeerTube returned an unexpected JSON response")
        return result

    @staticmethod
    def _video_reference(row):
        # The published list example omits id/uuid but includes embedPath.
        # Its final segment is the same UUID accepted by the video endpoints.
        return (
            row.get("id")
            or row.get("uuid")
            or (row.get("embedPath") or "").rsplit("/", 1)[-1]
            or None
        )

    async def _poll(self, credential, config):
        videos = config.operation == "on_new_channel_video"
        path = (
            "/api/v1/video-channels/"
            + quote(config.channel_handle, safe="")
            + "/videos"
            if videos
            else "/api/v1/video-channels"
        )
        items = []
        # Read the complete bounded scope before touching state; never silently
        # truncate a busy channel or mark unseen items consumed on a failed page.
        for start in range(0, 2000, 100):
            page = await self._request(
                credential,
                "GET",
                path,
                params={"start": start, "count": 100, "sort": "-createdAt"},
            )
            rows = page.get("data") if isinstance(page, dict) else None
            if not isinstance(rows, list) or any(
                not isinstance(row, dict)
                or (self._video_reference(row) if videos else row.get("id")) is None
                for row in rows
            ):
                raise ValueError("PeerTube list response is missing resource IDs")
            items.extend(rows)
            if len(rows) < 100:
                break
        else:
            raise ValueError(
                "PeerTube polling scope exceeds 2,000 items; use a smaller instance or channel"
            )
        fresh = await self._filter_unseen(
            items,
            lambda item: str(self._video_reference(item) if videos else item["id"]),
        )
        return {"videos" if videos else "channels": fresh, "new_item_count": len(fresh)}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict):
            return None
        videos = output.get("videos")
        channels = output.get("channels")
        rows = videos if isinstance(videos, list) else channels
        if not isinstance(rows, list) or not rows:
            return None
        lines = []
        for row in rows[:20]:
            if isinstance(videos, list):
                channel = row.get("channel") or {}
                account = row.get("account") or {}
                lines.append(
                    f"{row.get('name') or 'Untitled video'} — by {account.get('displayName') or account.get('name') or 'unknown creator'}, in {channel.get('displayName') or channel.get('name') or 'channel'}; video reference {cls._video_reference(row)}; published {row.get('publishedAt')}; {row.get('truncatedDescription') or ''}"
                )
            else:
                owner = row.get("ownerAccount") or {}
                lines.append(
                    f"{row.get('displayName') or row.get('name') or 'New channel'} — by {owner.get('displayName') or owner.get('name') or 'unknown creator'}; channel ID {row.get('id')}, host {row.get('host') or 'instance'}, name {row.get('name') or 'not supplied'}; {row.get('description') or ''}"
                )
        return {
            "text": f"PeerTube: {len(rows)} new {'video(s)' if isinstance(videos, list) else 'channel(s)'}\n"
            + "\n".join(lines),
            "conversation_key": None,
        }

    async def execute(self, inputs):
        config = self.config.config
        self.scope_registry.require(config.operation)
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a PeerTube instance and access token")
        if config.operation in {"on_new_channel_video", "on_new_channel"}:
            return await self._poll(credential, config)
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec["path"]
        for field in re.findall(r"\{([^}]+)\}", path):
            path = path.replace(
                "{" + field + "}", quote(str(values.pop(field)), safe="")
            )
        params = {key: values[key] for key in spec["query"] if key in values}
        body = {
            target: values[source]
            for source, target in spec["body"].items()
            if source in values
        }
        result = await self._request(
            credential,
            spec["method"],
            path,
            params=params or None,
            body=body or None,
            encoding=spec["encoding"],
        )
        if config.operation == "get_my_account":
            # The published contract describes a one-user array, while deployed
            # instances return the user object. Both retain the account's name.
            if isinstance(result, list) and len(result) == 1:
                result = result[0]
            if (
                not isinstance(result, dict)
                or not isinstance(result.get("username"), str)
                or not result["username"]
            ):
                raise ValueError("PeerTube account response is missing the username")
        return result if isinstance(result, dict) else {"data": result}
