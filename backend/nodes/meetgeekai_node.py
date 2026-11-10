"""MeetGeek's published v1 API using a person's pasted API key.

Each operation makes one documented API request and preserves the provider's
response fields. Webhook configuration is dashboard-only, outside this API.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

DOCS = "https://docs.meetgeek.ai/api"


class MeetGeekAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Meetgeek.ai API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.meetgeek.ai/integrations",
            "x-credential-instructions": "In MeetGeek, open Integrations → Public API and copy your API key. Paste the key without the Bearer prefix. Choose the API region used by your account.",
        })
    credential_type: Literal["meetgeekai_api_key"] = Field("meetgeekai_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, repr=False,
        json_schema_extra={"ui:widget": "password"})
    api_base_url: Literal["https://api.meetgeek.ai", "https://api-eu.meetgeek.ai", "https://api-us.meetgeek.ai"] = Field("https://api.meetgeek.ai", title="API region")

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value) or len(value) > 4096:
            raise ValueError("Paste the API key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(100, ge=1, le=500, title="Page size")
    cursor: str | None = Field(None, title="Page cursor", description="Use pagination.next_cursor from the previous response.")


class _Meeting(_Input):
    meeting_id: str = Field(..., min_length=1, max_length=512, title="Meeting", json_schema_extra={
        "x-dynamic-options": {"field_name": "meeting_id", "searchable": False, "allow_custom": True}})

    @field_validator("meeting_id")
    @classmethod
    def identifier(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value):
            raise ValueError("Use a MeetGeek meeting ID")
        return value


class ListMeetingsConfig(_Page):
    operation: Literal["list_meetings"] = Field("list_meetings", json_schema_extra={"ui:hidden": True, "x-display-name": "List Meetings"})


class GetMeetingConfig(_Meeting):
    operation: Literal["get_meeting"] = Field("get_meeting", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Meeting"})


class DeleteMeetingConfig(_Meeting):
    operation: Literal["delete_meeting"] = Field("delete_meeting", description="Permanently delete this meeting.", json_schema_extra={"ui:hidden": True, "x-display-name": "Delete Meeting"})


class GetInsightsConfig(_Meeting):
    operation: Literal["get_insights"] = Field("get_insights", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Meeting Insights"})


class GetHighlightsConfig(_Meeting):
    operation: Literal["get_highlights"] = Field("get_highlights", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Meeting Highlights"})
    type: str | None = Field(None, title="Highlight type", description="Optional highlight type, for example next_steps.")


class GetSummaryConfig(_Meeting):
    operation: Literal["get_summary"] = Field("get_summary", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Meeting Summary"})


class GetTranscriptConfig(_Meeting, _Page):
    operation: Literal["get_transcript"] = Field("get_transcript", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Meeting Transcript"})


class DownloadRecordingConfig(_Meeting):
    operation: Literal["download_recording"] = Field("download_recording", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Recording Download Link"})


class ListTeamsConfig(_Input):
    operation: Literal["list_teams"] = Field("list_teams", json_schema_extra={"ui:hidden": True, "x-display-name": "List Teams"})


class ListTeamMeetingsConfig(_Page):
    operation: Literal["list_team_meetings"] = Field("list_team_meetings", json_schema_extra={"ui:hidden": True, "x-display-name": "List Team Meetings"})
    team_id: int = Field(..., title="Team", json_schema_extra={
        "x-dynamic-options": {"field_name": "team_id", "searchable": False, "allow_custom": True}})


class _Analysis(_Input):
    language_code: str | None = Field(None, title="Language code", description="For example en-US; see MeetGeek's language-code appendix.")
    template_name: str | None = Field(None, title="Meeting template", description="For example General meeting; see MeetGeek's template appendix.")

    @field_validator("*", mode="after")
    @classmethod
    def link(cls, value, info):
        if info.field_name in {"join_link", "download_url"} and value:
            parsed = urlsplit(value)
            if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Use a public meeting or direct-download URL")
        return value


class JoinMeetingConfig(_Analysis):
    operation: Literal["join_meeting"] = Field("join_meeting", json_schema_extra={"ui:hidden": True, "x-display-name": "Send Bot to Meeting"})
    join_link: str = Field(..., min_length=1, title="Meeting join link")
    meeting_name: str | None = Field(None, title="Meeting name", description="Override the AI-generated title.")


class UploadRecordingConfig(_Analysis):
    operation: Literal["upload_recording"] = Field("upload_recording", json_schema_extra={"ui:hidden": True, "x-display-name": "Upload Recording for Analysis"})
    download_url: str = Field(..., min_length=1, title="Recording URL", description="Publicly accessible URL that starts a direct audio/video download. Acceptance does not mean analysis is complete.")


MeetGeekConfig = Annotated[Union[ListMeetingsConfig, GetMeetingConfig, DeleteMeetingConfig,
    GetInsightsConfig, GetHighlightsConfig, GetSummaryConfig, GetTranscriptConfig,
    DownloadRecordingConfig, ListTeamsConfig, ListTeamMeetingsConfig, JoinMeetingConfig,
    UploadRecordingConfig], Field(discriminator="operation")]


class MeetGeekNodeConfig(NodeConfig[MeetGeekConfig, MeetGeekAPIKeyCredential]):
    pass


# Route templates are a one-to-one map to the pinned OpenAPI operations.
ROUTES = {
    "list_meetings": ("GET", "/v1/meetings"),
    "get_meeting": ("GET", "/v1/meetings/{meeting_id}"),
    "delete_meeting": ("DELETE", "/v1/meetings/{meeting_id}"),
    "get_insights": ("GET", "/v1/meetings/{meeting_id}/insights"),
    "get_highlights": ("GET", "/v1/meetings/{meeting_id}/highlights"),
    "get_summary": ("GET", "/v1/meetings/{meeting_id}/summary"),
    "get_transcript": ("GET", "/v1/meetings/{meeting_id}/transcript"),
    "download_recording": ("POST", "/v1/meetings/{meeting_id}/download"),
    "list_teams": ("GET", "/v1/teams"),
    "list_team_meetings": ("GET", "/v1/teams/{team_id}/meetings"),
    "join_meeting": ("POST", "/v1/bot/join"),
    "upload_recording": ("POST", "/v1/upload"),
}


class MeetGeekNode(WorkflowNode):
    integration_type = "automation-meetgeekai"
    connection_evidence = ConnectionEvidence(operation="list_meetings", noun="meetings")

    @classmethod
    def get_config_model(cls):
        return MeetGeekNodeConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        from nodes.core.run_op import run_node_operation
        if field_name not in {"meeting_id", "team_id"}:
            raise ValueError("Unknown MeetGeek field")
        result = await run_node_operation(node_type=cls.integration_type,
            operation="list_meetings" if field_name == "meeting_id" else "list_teams",
            arguments={"cursor": page_token} if field_name == "meeting_id" and page_token else {},
            credential_data=credential_data, user_id="")
        if result.get("status") != "success":
            raise ValueError(result.get("message", "MeetGeek choices could not be loaded"))
        if field_name == "meeting_id":
            return {"options": [{"value": row["meeting_id"], "label": row["meeting_id"]} for row in result.get("meetings", [])],
                "next_page_token": result.get("pagination", {}).get("next_cursor")}
        rows = {str(row["id"]): row for key in ("share_access", "view_access") for row in result.get(key, [])}
        return {"options": [{"value": key, "label": row.get("name") or key} for key, row in rows.items()], "next_page_token": None}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a MeetGeek API key")
        credential = self.config.credentials
        config = self.config.config
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        method, route = ROUTES[config.operation]
        for key in ("meeting_id", "team_id"):
            if "{" + key + "}" in route:
                route = route.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        kwargs = {"params": values} if method == "GET" else ({"json": values} if values else {})
        async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, credential.api_base_url + route,
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}, **kwargs)
        expected = 202 if config.operation == "upload_recording" else 200
        if config.operation == "get_insights" and response.status_code == 204:
            output = {"status": "success", "http_status": 204, "has_content": False}
        elif response.status_code != expected:
            # Keep the provider's rejection visible to the connect-evidence seam.
            try:
                message = response.json().get("message", "MeetGeek request failed")
            except (ValueError, AttributeError):
                message = "MeetGeek request failed"
            message = str(message).replace(credential.api_key, "[redacted]")[:2000]
            return {"status": "error", "http_status": response.status_code, "message": message}
        elif config.operation == "delete_meeting":
            output = {"status": "success", "deleted": True, "meeting_id": config.meeting_id}
        else:
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("Expected a MeetGeek JSON object")
            output = {**body, "status": "success", "http_status": response.status_code}
        await self.emit(output)
        return output
