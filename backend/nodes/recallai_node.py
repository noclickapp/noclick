"""Recall.ai workspace meeting automation, pinned to its published meeting API.

Each operation makes one request. Pagination is explicit; media URLs are returned
as metadata and never downloaded. Bot status reads are on demand, not polling.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class RecallaiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Recall.ai API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.recall.ai/reference/authentication",
            "x-credential-instructions": "Paste your Recall.ai workspace API key and select the region shown in your Recall.ai dashboard. NoClick sends Token authorization only to that region. Keys are workspace-scoped; this connection does not identify an individual user.",
        })
    credential_type: Literal["recallai_api_key"] = Field("recallai_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})
    region: Literal["us-east-1", "us-west-2", "eu-central-1", "ap-northeast-1"] = Field("us-east-1", title="Workspace region")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your Recall.ai API key")
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without an Authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListBots(_Input):
    """List one page of workspace bots; do not use this to poll lifecycle status."""
    operation: Literal["list_bots"] = "list_bots"
    page: int = Field(1, ge=1)
    meeting_url: str | None = None
    join_at_after: date | None = None
    join_at_before: date | None = None


class _Bot(_Input):
    bot_id: UUID = Field(..., title="Bot ID")


class GetBot(_Bot):
    """Retrieve a bot on demand. Use provider webhooks for ongoing status changes."""
    operation: Literal["get_bot"] = "get_bot"


class CreateBot(_Input):
    """Send a bot now or schedule it to join a meeting; requires meeting recording consent."""
    operation: Literal["create_bot"] = "create_bot"
    meeting_url: HttpUrl
    bot_name: str | None = Field(None, min_length=1, max_length=100, description="Omit for the provider default: Meeting Notetaker.")
    join_at: datetime | None = Field(None, description="ISO 8601 time. Schedule at least 10 minutes ahead for production reliability; omit to join now.")
    metadata: dict[str, str] | None = None


class UpdateBot(_Bot):
    """Update a scheduled bot before it joins a call."""
    operation: Literal["update_bot"] = "update_bot"
    meeting_url: HttpUrl | None = None
    bot_name: str | None = Field(None, min_length=1, max_length=100)
    join_at: datetime | None = None
    metadata: dict[str, str] | None = None

    @model_validator(mode="after")
    def changed(self):
        if all(getattr(self, field) is None for field in ("meeting_url", "bot_name", "join_at", "metadata")):
            raise ValueError("Provide at least one scheduled bot field to update")
        return self


class DeleteBot(_Bot):
    """Delete a scheduled bot before it joins."""
    operation: Literal["delete_bot"] = "delete_bot"


class LeaveCall(_Bot):
    """Remove the bot from its current call."""
    operation: Literal["leave_call"] = "leave_call"


class PauseRecording(_Bot):
    """Pause a bot's ongoing recording."""
    operation: Literal["pause_recording"] = "pause_recording"


class ResumeRecording(_Bot):
    """Resume a bot's paused recording."""
    operation: Literal["resume_recording"] = "resume_recording"


class SendChatMessage(_Bot):
    """Send one meeting chat message. Only Zoom supports recipients other than everyone."""
    operation: Literal["send_chat_message"] = "send_chat_message"
    message: str = Field(..., min_length=1, max_length=4096)
    to: str | None = Field(None, min_length=1, description="Omit to send to everyone.")
    pin: bool = False


class _Cursor(_Input):
    cursor: str | None = Field(None, min_length=1, max_length=8192, description="Cursor from the previous page's next_cursor output.")


class ListRecordings(_Cursor):
    """List recording artifacts, optionally filtered by bot and creation time."""
    operation: Literal["list_recordings"] = "list_recordings"
    bot_id: UUID | None = None
    created_at_after: datetime | None = None
    created_at_before: datetime | None = None
    status_code: Literal["done", "failed", "paused", "processing"] | None = None


class _Recording(_Input):
    recording_id: UUID = Field(..., title="Recording ID")


class GetRecording(_Recording):
    """Get recording metadata and artifact download links without downloading media."""
    operation: Literal["get_recording"] = "get_recording"


class DeleteRecording(_Recording):
    """Permanently delete a recording and its artifacts."""
    operation: Literal["delete_recording"] = "delete_recording"


class ListTranscripts(_Cursor):
    """List transcript artifacts and their status, optionally filtered by recording."""
    operation: Literal["list_transcripts"] = "list_transcripts"
    recording_id: UUID | None = None
    created_at_after: datetime | None = None
    created_at_before: datetime | None = None
    status_code: Literal["done", "failed", "processing"] | None = None


class _Transcript(_Input):
    transcript_id: UUID = Field(..., title="Transcript ID")


class GetTranscript(_Transcript):
    """Retrieve transcript artifact metadata and its download URL, not transcript text."""
    operation: Literal["get_transcript"] = "get_transcript"


class DeleteTranscript(_Transcript):
    """Permanently delete a transcript artifact."""
    operation: Literal["delete_transcript"] = "delete_transcript"


class ListCalendars(_Cursor):
    """List calendar connections already linked in the Recall.ai workspace."""
    operation: Literal["list_calendars"] = "list_calendars"
    email: str | None = None
    platform: Literal["google_calendar", "microsoft_outlook"] | None = None
    status: Literal["connected", "connecting", "disconnected"] | None = None
    created_at__gte: datetime | None = None


class _Calendar(_Input):
    calendar_id: UUID = Field(..., title="Calendar ID")


class GetCalendar(_Calendar):
    """Get a linked calendar's metadata and sync status."""
    operation: Literal["get_calendar"] = "get_calendar"


class DeleteCalendar(_Calendar):
    """Delete an existing calendar connection."""
    operation: Literal["delete_calendar"] = "delete_calendar"


class ListCalendarEvents(_Cursor):
    """List one linked calendar's events."""
    operation: Literal["list_calendar_events"] = "list_calendar_events"
    calendar_id: UUID = Field(..., title="Calendar ID")
    ical_uid: str | None = None
    is_deleted: bool | None = None
    start_time__gte: datetime | None = None
    start_time__lte: datetime | None = None


class GetCalendarEvent(_Input):
    """Get the meeting details of a calendar event."""
    operation: Literal["get_calendar_event"] = "get_calendar_event"
    event_id: UUID = Field(..., title="Calendar event ID")


RecallaiOperation = Annotated[Union[
    ListBots, GetBot, CreateBot, UpdateBot, DeleteBot, LeaveCall,
    PauseRecording, ResumeRecording, SendChatMessage, ListRecordings,
    GetRecording, DeleteRecording, ListTranscripts, GetTranscript,
    DeleteTranscript, ListCalendars, GetCalendar, DeleteCalendar,
    ListCalendarEvents, GetCalendarEvent,
], Field(discriminator="operation")]


class RecallaiConfig(NodeConfig[RecallaiOperation, RecallaiAPIKeyCredential]):
    pass


# (method, fixed route, path ID field). No arbitrary URL or method operation.
ROUTES = {
    "list_bots": ("GET", "/api/v1/bot/", None),
    "get_bot": ("GET", "/api/v1/bot/{id}/", "bot_id"),
    "create_bot": ("POST", "/api/v1/bot/", None),
    "update_bot": ("PATCH", "/api/v1/bot/{id}/", "bot_id"),
    "delete_bot": ("DELETE", "/api/v1/bot/{id}/", "bot_id"),
    "leave_call": ("POST", "/api/v1/bot/{id}/leave_call/", "bot_id"),
    "pause_recording": ("POST", "/api/v1/bot/{id}/pause_recording/", "bot_id"),
    "resume_recording": ("POST", "/api/v1/bot/{id}/resume_recording/", "bot_id"),
    "send_chat_message": ("POST", "/api/v1/bot/{id}/send_chat_message/", "bot_id"),
    "list_recordings": ("GET", "/api/v1/recording/", None),
    "get_recording": ("GET", "/api/v1/recording/{id}/", "recording_id"),
    "delete_recording": ("DELETE", "/api/v1/recording/{id}/", "recording_id"),
    "list_transcripts": ("GET", "/api/v1/transcript/", None),
    "get_transcript": ("GET", "/api/v1/transcript/{id}/", "transcript_id"),
    "delete_transcript": ("DELETE", "/api/v1/transcript/{id}/", "transcript_id"),
    "list_calendars": ("GET", "/api/v2/calendars/", None),
    "get_calendar": ("GET", "/api/v2/calendars/{id}/", "calendar_id"),
    "delete_calendar": ("DELETE", "/api/v2/calendars/{id}/", "calendar_id"),
    "list_calendar_events": ("GET", "/api/v2/calendar-events/", None),
    "get_calendar_event": ("GET", "/api/v2/calendar-events/{id}/", "event_id"),
}
BODY_OPERATIONS = {"create_bot", "update_bot", "send_chat_message"}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {str(key).replace(secret, "[redacted]"): (
            "[redacted]" if str(key).lower() in {"api_key", "access_token", "refresh_token", "oauth_client_secret", "oauth_refresh_token", "oauth_access_token", "client_secret"}
            else _redact(item, secret)) for key, item in value.items()}
    return value


class RecallaiNode(WorkflowNode):
    integration_type = "automation-recallai"
    connection_evidence = ConnectionEvidence(noun="workspace meeting bots", operation="list_bots", label_keys=("bot_name", "id"))

    @classmethod
    def get_config_model(cls):
        return RecallaiConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Recall.ai API key")
        credential = self.config.credentials
        op = self.config.config
        action = op.operation
        method, route, id_field = ROUTES[action]
        values = op.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        if id_field:
            route = route.replace("{id}", values.pop(id_field))
        origin = f"https://{credential.region}.recall.ai"
        params = values if method == "GET" else None
        body = values if action in BODY_OPERATIONS else None
        if params:
            params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in params.items()}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, origin + route, params=params, json=body,
                    headers={"Authorization": "Token " + credential.api_key, "Accept": "application/json"})
        except httpx.RequestError:
            # A write can reach the provider even when the response is lost. Never retry automatically.
            raise ValueError("Recall.ai request could not be confirmed" + ("; inspect the resource before retrying this write" if method != "GET" else "")) from None
        if not 200 <= response.status_code < 300:
            message = _redact(response.text[:2000], credential.api_key)
            raise ValueError(f"Recall.ai HTTP {response.status_code}: {message}")
        result = {"status": "success", "operation": action, "http_status": response.status_code}
        if response.status_code == 204:
            result.update(acknowledged=True, deleted_id=str(getattr(op, id_field)), absence_verified=False)
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Recall.ai returned an unexpected non-JSON response; inspect before retrying a write") from None
            if not isinstance(data, dict):
                raise ValueError("Recall.ai returned an unexpected response shape")
            if action.startswith("list_"):
                if not isinstance(data.get("results"), list):
                    raise ValueError("Recall.ai returned an unexpected list envelope")
                result.update(data=data["results"], next=data.get("next"), previous=data.get("previous"), complete=not bool(data.get("next")))
                if "count" in data:
                    result["count"] = data["count"]
                # Parse the continuation only as data. Never follow a response URL.
                next_url = data.get("next")
                if isinstance(next_url, str):
                    query = parse_qs(urlsplit(next_url).query)
                    if action == "list_bots":
                        page = query.get("page", [None])[0]
                        result["next_page"] = int(page) if page and page.isdecimal() else None
                    else:
                        result["next_cursor"] = query.get("cursor", [None])[0]
            else:
                result["data"] = data
                if method != "GET":
                    result["acknowledged"] = True
        result = _redact(result, credential.api_key)
        await self.emit(result)
        return result
