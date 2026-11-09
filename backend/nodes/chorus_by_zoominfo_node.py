"""Chorus API 26.45.03: one documented endpoint per operation.

Personal tokens use the published bearer-token security scheme. List operations return one page; continuation
keys and JSON:API links remain in data and are never followed automatically.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://chorus.ai"


class ChorusAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Chorus API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://chorus.ai/login",
            "x-credential-instructions": "In Chorus Personal Settings, generate a personal API token. Your Chorus role must permit API access. Paste only the token; NoClick sends it in the Authorization header. API access follows your user's data visibility and action permissions.",
        })
    credential_type: Literal["chorus_by_zoominfo_api_token"] = Field("chorus_by_zoominfo_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the Chorus API token without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _ID(_Input):
    id: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", description="Exact Chorus resource ID.")


class GetCurrentUser(_Input):
    """Get current user."""
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})


class ListUsers(_Input):
    """List users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})


class ListEngagements(_Input):
    """List engagements."""
    operation: Literal["list_engagements"] = Field("list_engagements", json_schema_extra={"ui:hidden": True})
    continuation_key: str | None = Field(None, description="Copy the previous page's continuation_key to fetch the next page.")
    engagement_id: str | None = Field(None, description="Comma-separated engagement IDs.")
    engagement_type: Literal["meeting", "dialer", "email", "content_viewed", "unrecorded_meeting"] | None = None
    min_date: datetime | None = Field(None, description="Minimum engagement date, ISO 8601 date-time.")
    max_date: datetime | None = Field(None, description="Maximum engagement date, ISO 8601 date-time.")
    participants_email: str | None = None
    team_id: str | None = Field(None, description="Comma-separated owner team IDs.")
    user_id: str | None = Field(None, description="Comma-separated owner user IDs.")
    with_trackers: bool = False


class GetConversation(_ID):
    """Get conversation."""
    operation: Literal["get_conversation"] = Field("get_conversation", json_schema_extra={"ui:hidden": True})
    fields: str | None = Field(None, description="Comma-separated documented fields, e.g. name,recording.utterances,recording.trackers.")
    include_meeting_metadata: bool = False


class DeleteEngagement(_Input):
    """Request asynchronous deletion of a single engagement."""
    operation: Literal["delete_engagement"] = Field("delete_engagement", json_schema_extra={"ui:hidden": True})
    engagement_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", description="Exact engagement ID to delete asynchronously.")


class ListTeams(_Input):
    """List teams."""
    operation: Literal["list_teams"] = Field("list_teams", json_schema_extra={"ui:hidden": True})


class GetTeam(_ID):
    """Get team."""
    operation: Literal["get_team"] = Field("get_team", json_schema_extra={"ui:hidden": True})


class ListPlaylists(_Input):
    """List playlists."""
    operation: Literal["list_playlists"] = Field("list_playlists", json_schema_extra={"ui:hidden": True})
    page_number: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=1000)
    name: str | None = None
    conversation_id: str | None = None
    subscribed: bool | None = None


class GetPlaylist(_ID):
    """Get playlist."""
    operation: Literal["get_playlist"] = Field("get_playlist", json_schema_extra={"ui:hidden": True})


class CreatePlaylist(_Input):
    """Create playlist."""
    operation: Literal["create_playlist"] = Field("create_playlist", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    description: str | None = None
    parent: int | None = None


class DeletePlaylist(_ID):
    """Delete a playlist without recursively deleting children."""
    operation: Literal["delete_playlist"] = Field("delete_playlist", json_schema_extra={"ui:hidden": True})


class ListMoments(_Input):
    """List moments."""
    operation: Literal["list_moments"] = Field("list_moments", json_schema_extra={"ui:hidden": True})
    shared_on: str = Field(..., description="Required date range; e.g. 2021-01-01T00:00:00Z:2021-01-31T00:00:00Z. Maximum range 365 days.")


class CreateMoment(_Input):
    """Create moment."""
    operation: Literal["create_moment"] = Field("create_moment", json_schema_extra={"ui:hidden": True})
    callid: str = Field(..., min_length=1)
    moment_time: float = Field(..., ge=0, description="Start time in seconds.")
    moment_duration: float = Field(..., gt=0, description="Duration in seconds.")
    subject: str | None = None
    note: str | None = None
    url_string: str | None = None
    expiration_date: str | None = None


class UpdateMoment(_ID):
    """Update moment."""
    operation: Literal["update_moment"] = Field("update_moment", json_schema_extra={"ui:hidden": True})
    moment_time: float | None = Field(None, ge=0)
    moment_duration: float | None = Field(None, gt=0)
    subject: str | None = None
    note: str | None = None
    url_string: str | None = None
    expiration_date: str | None = None


class DeleteMoment(_ID):
    """Delete moment."""
    operation: Literal["delete_moment"] = Field("delete_moment", json_schema_extra={"ui:hidden": True})


class ListWebhooks(_Input):
    """List webhooks."""
    operation: Literal["list_webhooks"] = Field("list_webhooks", json_schema_extra={"ui:hidden": True})


class CreateWebhook(_Input):
    """Create webhook."""
    operation: Literal["create_webhook"] = Field("create_webhook", json_schema_extra={"ui:hidden": True})
    event: Literal["recording_done"] = Field("recording_done")
    hook_url: str = Field(..., min_length=1, description="Webhook callback URL that Chorus should post to.")


class DeleteWebhook(_Input):
    """Delete webhook."""
    operation: Literal["delete_webhook"] = Field("delete_webhook", json_schema_extra={"ui:hidden": True})
    hook_url: str = Field(..., min_length=1, description="Exact URL of the webhook to delete.")


class UploadRecording(_Input):
    """Upload recording."""
    operation: Literal["upload_recording"] = Field("upload_recording", json_schema_extra={"ui:hidden": True})
    data: str = Field(..., description="Recording file: public HTTPS URL or data URI. Formats: 3GPP, AU, AVI, FLV, HLS, MKV, MP3, MP4, Ogg, WAV, WebM.", json_schema_extra={"format": "data-url", "accept": "audio/*,video/*"})
    name: str = Field(..., min_length=1, description="Recording name.")
    user: str = Field(..., min_length=1, description="Recording owner's email address.")
    meeting_id: str | None = None
    crm_account_id: str | None = None
    crm_opportunity_id: str | None = None


ChorusOperation = Annotated[Union[
    GetCurrentUser, ListUsers, ListEngagements, GetConversation, DeleteEngagement, ListTeams, GetTeam, ListPlaylists, GetPlaylist, CreatePlaylist, DeletePlaylist, ListMoments, CreateMoment, UpdateMoment, DeleteMoment, ListWebhooks, CreateWebhook, DeleteWebhook, UploadRecording
], Field(discriminator="operation")]


class ChorusNodeConfig(NodeConfig[ChorusOperation, ChorusAPITokenCredential]):
    pass


ROUTES = {'get_current_user': ('GET', '/api/v1/users/me'), 'list_users': ('GET', '/v3/users'), 'list_engagements': ('GET', '/v3/engagements'), 'get_conversation': ('GET', '/api/v1/conversations/{id}'), 'delete_engagement': ('DELETE', '/v3/engagements/{engagement_id}'), 'list_teams': ('GET', '/api/v1/teams'), 'get_team': ('GET', '/api/v1/teams/{id}'), 'list_playlists': ('GET', '/api/v1/playlists'), 'get_playlist': ('GET', '/api/v1/playlists/{id}'), 'create_playlist': ('POST', '/api/v1/playlists'), 'delete_playlist': ('DELETE', '/api/v1/playlists/{id}'), 'list_moments': ('GET', '/api/v1/moments'), 'create_moment': ('POST', '/api/v1/moments'), 'update_moment': ('PUT', '/api/v1/moments/{id}'), 'delete_moment': ('DELETE', '/api/v1/moments/{id}'), 'list_webhooks': ('GET', '/v3/webhook'), 'create_webhook': ('POST', '/v3/webhook'), 'delete_webhook': ('DELETE', '/v3/webhook'), 'upload_recording': ('POST', '/v3/upload')}
WIRE_NAMES = {"page_number": "page[number]", "page_size": "page[size]", "conversation_id": "filter[conversation]",
              "name": "filter[name]", "subscribed": "filter[subscribed]", "shared_on": "filter[shared_on]"}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items() if k.lower() not in {"password", "api_token", "access_token", "authorization"}}
    return value


class ChorusByZoomInfoNode(WorkflowNode):
    integration_type = "automation-chorus-by-zoominfo"
    connection_evidence = ConnectionEvidence(identity_operation="get_current_user", noun="Chorus account", label_keys=("name", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return ChorusNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Chorus by ZoomInfo API token")
        credential = self.config.credentials
        op = self.config.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        identifier = None
        for field in ("id", "engagement_id"):
            if "{" + field + "}" in path:
                identifier = values.pop(field)
                path = path.replace("{" + field + "}", quote(identifier, safe=""))
        params, body, files = None, None, None
        media = "application/vnd.api+json" if path.startswith("/api/") else "application/json"
        headers = {"Authorization": "Bearer " + credential.api_token, "Accept": media}
        if method == "GET":
            params = {WIRE_NAMES.get(k, k): str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
        elif op.operation == "upload_recording":
            from nodes.core.media_resolver import resolve_media_input
            resolved = await resolve_media_input(values.pop("data"), default_mime="application/octet-stream")
            files = {k: (None, str(v).lower() if isinstance(v, bool) else str(v)) for k, v in values.items()}
            files["data"] = (resolved.filename or "recording", resolved.data, resolved.mime_type)
        elif op.operation in {"create_playlist", "create_moment", "update_moment"}:
            resource_type = {"create_playlist": "playlist", "create_moment": "moment_create_request", "update_moment": "moment_edit_request"}[op.operation]
            body = {"data": {"type": resource_type, "attributes": values}}
            if identifier is not None:
                body["data"]["id"] = identifier
        elif values:
            body = values
        if body is not None:
            headers["Content-Type"] = media
        async with guarded_async_client(timeout=120, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, headers=headers, params=params, json=body, files=files)
        if not 200 <= response.status_code < 300:
            message = _redact(response.text[:2000], credential.api_token)
            raise ValueError(f"Chorus HTTP {response.status_code}: {message}")
        if response.status_code == 204 or not response.content:
            data = None
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Chorus returned invalid JSON") from None
            if path.startswith("/api/") and not isinstance(data, (dict, list)):
                raise ValueError("Chorus returned an unexpected response shape")
            if isinstance(data, dict) and data.get("errors"):
                raise ValueError("Chorus: " + str(_redact(data["errors"], credential.api_token)))
        output = {"status": "success", "data": _redact(data, credential.api_token), "http_status": response.status_code}
        if response.status_code == 202:
            output["accepted_for_processing"] = True
        if method == "DELETE" and response.status_code == 204:
            output["deletion_acknowledged"] = True
        await self.emit(output)
        return output
