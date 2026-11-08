"""Daily REST API v1 (published OpenAPI 1.1.1).

Each operation makes exactly one request. Lists return one page; pass Daily's
opaque IDs as cursors to continue. Access links are returned, never downloaded.
"""
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.daily.co/v1"


class DailyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Daily API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://dashboard.daily.co/developers",
        "x-credential-instructions": "Copy your API key from the Daily dashboard Developers page. Paste only the key, without Bearer. NoClick sends it to api.daily.co. The connection check reads rooms in your Daily domain; recording and analytics availability depends on your account."})
    credential_type: Literal["daily_api_key"] = Field("daily_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without Bearer or whitespace")
        return value


class DailyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifiers(cls, value, info):
        if value is not None and info.field_name in {
            "room_name", "name", "recording_id", "meeting_id", "meeting_token",
            "starting_after", "ending_before", "joined_after", "joined_before",
        }:
            if not isinstance(value, str) or not value or len(value) > 4096 or value in {".", ".."} or any(
                c in "/?#\\" or c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value
            ):
                raise ValueError("Use a single Daily name, ID, token or cursor without URL separators")
        return value


class DailyPage(DailyInput):
    limit: int = Field(100, ge=1, le=100, description="Maximum rows in this page. Lists never fetch subsequent pages automatically.")
    starting_after: Optional[str] = Field(None, description="Daily object ID to continue after. Mutually exclusive with ending_before.")
    ending_before: Optional[str] = Field(None, description="Daily object ID to continue before.")

    @model_validator(mode="after")
    def direction(self):
        if self.starting_after and self.ending_before:
            raise ValueError("Choose one pagination direction")
        return self


class DailyListRooms(DailyPage):
    """List rooms in your Daily domain, one page at a time."""
    operation: Literal["list_rooms"] = "list_rooms"


class DailyRoom(DailyInput):
    room_name: str = Field(..., title="Room name", description="The room name, not its URL.")


class DailyGetRoom(DailyRoom):
    """Get a room's configuration and URL."""
    operation: Literal["get_room"] = "get_room"


class DailyRoomSettings(DailyInput):
    privacy: Optional[Literal["public", "private"]] = None
    nbf: Optional[int] = Field(None, ge=0, le=2147483647, description="Not before, Unix seconds.")
    exp: Optional[int] = Field(None, ge=0, le=2147483647, description="Room expiry, Unix seconds.")
    max_participants: Optional[int] = Field(None, ge=1, le=200)
    enable_chat: Optional[StrictBool] = None
    enable_screenshare: Optional[StrictBool] = None
    enable_knocking: Optional[StrictBool] = None
    start_video_off: Optional[StrictBool] = None
    start_audio_off: Optional[StrictBool] = None
    eject_at_room_exp: Optional[StrictBool] = None
    enable_recording: Optional[Literal["cloud", "cloud-audio-only", "local", "raw-tracks"]] = Field(
        None, description="Enable recording capability. Cloud recording may incur Daily charges; this does not start a recording.")

    @model_validator(mode="after")
    def times(self):
        if self.nbf is not None and self.exp is not None and self.nbf >= self.exp:
            raise ValueError("Expiry must be after not-before")
        return self


class DailyCreateRoom(DailyRoomSettings):
    """Create a room. Omit name to let Daily generate one."""
    operation: Literal["create_room"] = "create_room"
    name: Optional[str] = Field(None, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class DailyUpdateRoom(DailyRoomSettings, DailyRoom):
    """Update supplied room settings; omitted settings stay unchanged."""
    operation: Literal["update_room"] = "update_room"


class DailyDeleteRoom(DailyRoom):
    """Permanently delete a room and its URL."""
    operation: Literal["delete_room"] = "delete_room"


class DailyRoomPresence(DailyRoom):
    """Read the current participants in a room, one bounded page."""
    operation: Literal["get_room_presence"] = "get_room_presence"
    limit: int = Field(100, ge=1, le=100)
    userId: Optional[str] = Field(None, title="User ID filter")
    userName: Optional[str] = Field(None, title="User name filter")


class DailyCreateMeetingToken(DailyRoom):
    """Create an expiring token restricted to one room. Treat the result as a secret."""
    operation: Literal["create_meeting_token"] = "create_meeting_token"
    exp: int = Field(..., ge=1, le=2147483647, description="Token expiry as Unix seconds. Choose a future time.")
    nbf: Optional[int] = Field(None, ge=0, le=2147483647)
    is_owner: StrictBool = Field(False, description="Grant meeting owner administration privileges.")
    user_name: Optional[str] = None
    user_id: Optional[str] = Field(None, max_length=36)
    eject_at_token_exp: Optional[StrictBool] = None
    start_video_off: Optional[StrictBool] = None
    start_audio_off: Optional[StrictBool] = None

    @model_validator(mode="after")
    def times(self):
        if self.nbf is not None and self.nbf >= self.exp:
            raise ValueError("Token expiry must be after not-before")
        return self


class DailyValidateMeetingToken(DailyInput):
    """Validate a meeting token and read its permissions."""
    operation: Literal["validate_meeting_token"] = "validate_meeting_token"
    meeting_token: str = Field(..., json_schema_extra={"ui:widget": "password"})
    ignoreNbf: Optional[StrictBool] = Field(None, title="Ignore not-before time")


class DailyListRecordings(DailyPage):
    """List recording metadata, optionally filtered by room."""
    operation: Literal["list_recordings"] = "list_recordings"
    room_name: Optional[str] = None


class DailyRecording(DailyInput):
    recording_id: str = Field(..., title="Recording ID")


class DailyGetRecording(DailyRecording):
    """Get recording metadata, tracks and storage details."""
    operation: Literal["get_recording"] = "get_recording"


class DailyDeleteRecording(DailyRecording):
    """Delete a recording. Customer-managed storage may require separate file deletion."""
    operation: Literal["delete_recording"] = "delete_recording"


class DailyRecordingLink(DailyRecording):
    """Get a temporary recording download link. Use Daily's returned expires timestamp."""
    operation: Literal["get_recording_link"] = "get_recording_link"
    valid_for_secs: int = Field(3600, ge=900, le=43200,
        description="Requested lifetime. Daily may cap it for customer S3 storage; the returned expires is authoritative.")


class DailyListMeetings(DailyPage):
    """List meeting sessions and attendance with optional room and time filters."""
    operation: Literal["list_meetings"] = "list_meetings"
    room: Optional[list[str]] = Field(None, max_length=100, description="Room names; sent as repeated room query parameters.")
    timeframe_start: Optional[int] = Field(None, ge=0, le=2147483647)
    timeframe_end: Optional[int] = Field(None, ge=0, le=2147483647)
    ongoing: Optional[StrictBool] = None
    no_participants: Optional[StrictBool] = None

    @model_validator(mode="after")
    def times(self):
        if self.timeframe_start is not None and self.timeframe_end is not None and self.timeframe_start >= self.timeframe_end:
            raise ValueError("Timeframe end must be after start")
        return self


class DailyMeeting(DailyInput):
    meeting_id: str = Field(..., title="Meeting session ID")


class DailyGetMeeting(DailyMeeting):
    """Get one meeting session's analytics."""
    operation: Literal["get_meeting"] = "get_meeting"


class DailyMeetingParticipants(DailyMeeting):
    """List attendance records for one meeting, using participant IDs as cursors."""
    operation: Literal["list_meeting_participants"] = "list_meeting_participants"
    limit: int = Field(100, ge=1, le=100)
    joined_after: Optional[str] = None
    joined_before: Optional[str] = None

    @model_validator(mode="after")
    def direction(self):
        if self.joined_after and self.joined_before:
            raise ValueError("Choose one participant pagination direction")
        return self


class DailyGetPresence(DailyInput):
    """Get a map of active participants across rooms in this domain."""
    operation: Literal["get_presence"] = "get_presence"


class DailyGetDomain(DailyInput):
    """Read the API key's Daily domain configuration."""
    operation: Literal["get_domain"] = "get_domain"


DailyOperation = Annotated[Union[
    DailyListRooms, DailyGetRoom, DailyCreateRoom, DailyUpdateRoom, DailyDeleteRoom, DailyRoomPresence,
    DailyCreateMeetingToken, DailyValidateMeetingToken, DailyListRecordings, DailyGetRecording,
    DailyDeleteRecording, DailyRecordingLink, DailyListMeetings, DailyGetMeeting,
    DailyMeetingParticipants, DailyGetPresence, DailyGetDomain,
], Field(discriminator="operation")]


class DailyFullConfig(NodeConfig[DailyOperation, DailyAPIKeyCredential]):
    pass


# Fixed methods and paths: no generic request operation and no caller-supplied host.
ROUTES = {
    "list_rooms": ("GET", "/rooms"), "get_room": ("GET", "/rooms/{room_name}"),
    "create_room": ("POST", "/rooms"), "update_room": ("POST", "/rooms/{room_name}"),
    "delete_room": ("DELETE", "/rooms/{room_name}"),
    "get_room_presence": ("GET", "/rooms/{room_name}/presence"),
    "create_meeting_token": ("POST", "/meeting-tokens"),
    "validate_meeting_token": ("GET", "/meeting-tokens/{meeting_token}"),
    "list_recordings": ("GET", "/recordings"), "get_recording": ("GET", "/recordings/{recording_id}"),
    "delete_recording": ("DELETE", "/recordings/{recording_id}"),
    "get_recording_link": ("GET", "/recordings/{recording_id}/access-link"),
    "list_meetings": ("GET", "/meetings"), "get_meeting": ("GET", "/meetings/{meeting_id}"),
    "list_meeting_participants": ("GET", "/meetings/{meeting_id}/participants"),
    "get_presence": ("GET", "/presence"), "get_domain": ("GET", "/"),
}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items()}
    return value


class DailyNode(WorkflowNode):
    integration_type = "automation-daily"
    connection_evidence = ConnectionEvidence(noun="Daily rooms", operation="list_rooms", label_keys=("name", "url", "id"))

    @classmethod
    def get_config_model(cls):
        return DailyFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Daily API key")
        op = self.config.config
        action = op.operation
        method, path = ROUTES[action]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for field in ("room_name", "recording_id", "meeting_id", "meeting_token"):
            placeholder = "{" + field + "}"
            if placeholder in path:
                path = path.replace(placeholder, quote(values.pop(field), safe=""))
        params, body = values, None
        if action in {"create_room", "update_room"}:
            body = {key: values.pop(key) for key in ("name", "privacy") if key in values}
            if values:
                body["properties"] = values.copy()
            params = {}
            if action == "update_room" and not body:
                raise ValueError("Supply at least one room setting")
        elif action == "create_meeting_token":
            body, params = {"properties": values}, {}
        params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in params.items()}
        key = self.config.credentials.api_key
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params, **({"json": body} if body is not None else {}),
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
        except httpx.RequestError:
            raise ValueError("Daily request could not be confirmed; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            # Preserve provider rejections for the shared manual-connect verdict.
            try:
                error = response.json()
                message = error.get("info") or error.get("error") or error.get("message") if isinstance(error, dict) else None
            except ValueError:
                message = None
            raise ValueError(_redact(f"Daily HTTP {response.status_code}: {str(message)[:1000] if message else 'request rejected'}", key)) from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Daily returned an unreadable response; inspect writes before retrying") from None
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError("Daily returned an unexpected response; inspect writes before retrying")
        if action.startswith("list_") or action == "get_room_presence":
            if not isinstance(payload.get("data"), list):
                raise ValueError("Daily returned an invalid page")
            output = {"status": "success", **payload, "page_only": True}
        else:
            output = {"status": "success", "data": payload}
        output = _redact(output, key)
        await self.emit(output)
        return output
