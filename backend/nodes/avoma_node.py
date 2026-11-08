"""Avoma API 1.0.0: one published endpoint per operation.

Contract: https://dev.avoma.com/openapi.yml. Paginated reads return one page,
including the provider's count/next/previous metadata; URLs are never followed.
"""
from datetime import datetime
from typing import Annotated, Literal, Union
from uuid import UUID
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.avoma.com"


class AvomaAPIKey(BaseModel):
    model_config = ConfigDict(title="Avoma API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://help.avoma.com/api-integration-for-avoma",
        "x-credential-instructions": "Ask an Avoma organization admin to open Settings → Organization → Developer and copy the full API key (CLIENT_KEY:CLIENT_SECRET). Paste it here without the Bearer prefix. Choose the minimum user or organization access needed. NoClick reads users to check the connection; that check does not prove access to every meeting or write operation."})
    credential_type: Literal["avoma_api_key"] = Field("avoma_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the full API key without the Bearer prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class DateRange(Input):
    from_date: datetime = Field(..., description="Inclusive start of the UTC meeting date range (RFC3339).")
    to_date: datetime = Field(..., description="Inclusive end of the UTC meeting date range (RFC3339).")

    @model_validator(mode="after")
    def date_range(self):
        if self.from_date.tzinfo is None or self.to_date.tzinfo is None:
            raise ValueError("Include a UTC offset in both dates")
        if self.to_date < self.from_date:
            raise ValueError("End date must be on or after start date")
        return self


class LabelBody(Input):
    label: str = Field(..., min_length=1, max_length=64)
    description: str = Field(..., description="Description of the meeting type or outcome.")


class LabelUpdate(Input):
    label: str | None = Field(None, min_length=1, max_length=64)
    description: str | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if self.label is None and self.description is None:
            raise ValueError("Provide a label or description to update")
        return self


class ListMeetings(DateRange):
    """List meetings."""
    operation: Literal["list_meetings"] = Field("list_meetings", json_schema_extra={"ui:hidden": True})
    page_size: int = Field(10, ge=1, le=100)
    is_call: bool | None = None
    is_internal: bool | None = None
    attendee_emails: str | None = None
    include_crm_associations: bool = False
    o: Literal["start_at", "-start_at"] = "-start_at"


class GetMeeting(Input):
    """Get meeting."""
    operation: Literal["get_meeting"] = Field("get_meeting", json_schema_extra={"ui:hidden": True})
    uuid: UUID
    include_crm_associations: bool = False


class GetMeetingInsights(Input):
    """Get meeting insights."""
    operation: Literal["get_meeting_insights"] = Field("get_meeting_insights", json_schema_extra={"ui:hidden": True})
    meeting_uuid: UUID


class ListNotes(DateRange):
    """List notes."""
    operation: Literal["list_notes"] = Field("list_notes", json_schema_extra={"ui:hidden": True})
    page_size: int = Field(5, ge=1, le=20)
    meeting_uuid: UUID | None = None
    custom_category: UUID | None = None
    output_format: Literal["json", "html", "markdown"] = "json"
    o: Literal["start_at", "-start_at", "modified", "-modified"] = "-start_at"


class GetRecording(Input):
    """Get recording."""
    operation: Literal["get_recording"] = Field("get_recording", json_schema_extra={"ui:hidden": True})
    meeting_uuid: UUID


class ListTranscriptions(DateRange):
    """List transcriptions."""
    operation: Literal["list_transcriptions"] = Field("list_transcriptions", json_schema_extra={"ui:hidden": True})
    meeting_uuid: UUID | None = None
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    attendee_emails: str | None = None


class GetTranscription(Input):
    """Get transcription."""
    operation: Literal["get_transcription"] = Field("get_transcription", json_schema_extra={"ui:hidden": True})
    uuid: UUID


class ListUsers(Input):
    """List users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})


class GetUser(Input):
    """Get user."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    uuid: UUID


class ListSmartCategories(Input):
    """List smart categories."""
    operation: Literal["list_smart_categories"] = Field("list_smart_categories", json_schema_extra={"ui:hidden": True})
    o: Literal["start_at", "-start_at", "modified", "-modified", "name", "-name", "background_color", "-background_color"] = "-start_at"


class GetSmartCategory(Input):
    """Get smart category."""
    operation: Literal["get_smart_category"] = Field("get_smart_category", json_schema_extra={"ui:hidden": True})
    uuid: UUID


class ListTemplates(Input):
    """List templates."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})


class GetTemplate(Input):
    """Get template."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})
    uuid: UUID


class ListMeetingTypes(Input):
    """List meeting types."""
    operation: Literal["list_meeting_types"] = Field("list_meeting_types", json_schema_extra={"ui:hidden": True})


class GetMeetingType(Input):
    """Get meeting type."""
    operation: Literal["get_meeting_type"] = Field("get_meeting_type", json_schema_extra={"ui:hidden": True})
    uuid: UUID


class CreateMeetingType(LabelBody):
    """Create meeting type."""
    operation: Literal["create_meeting_type"] = Field("create_meeting_type", json_schema_extra={"ui:hidden": True})


class UpdateMeetingType(LabelUpdate):
    """Update meeting type."""
    operation: Literal["update_meeting_type"] = Field("update_meeting_type", json_schema_extra={"ui:hidden": True})
    uuid: UUID


class DeleteMeetingType(Input):
    """Delete meeting type."""
    operation: Literal["delete_meeting_type"] = Field("delete_meeting_type", json_schema_extra={"ui:hidden": True})
    uuid: UUID


class ListMeetingOutcomes(Input):
    """List meeting outcomes."""
    operation: Literal["list_meeting_outcomes"] = Field("list_meeting_outcomes", json_schema_extra={"ui:hidden": True})


class GetMeetingOutcome(Input):
    """Get meeting outcome."""
    operation: Literal["get_meeting_outcome"] = Field("get_meeting_outcome", json_schema_extra={"ui:hidden": True})
    uuid: UUID


class CreateMeetingOutcome(LabelBody):
    """Create meeting outcome."""
    operation: Literal["create_meeting_outcome"] = Field("create_meeting_outcome", json_schema_extra={"ui:hidden": True})


class UpdateMeetingOutcome(LabelUpdate):
    """Update meeting outcome."""
    operation: Literal["update_meeting_outcome"] = Field("update_meeting_outcome", json_schema_extra={"ui:hidden": True})
    uuid: UUID


class DeleteMeetingOutcome(Input):
    """Delete meeting outcome."""
    operation: Literal["delete_meeting_outcome"] = Field("delete_meeting_outcome", json_schema_extra={"ui:hidden": True})
    uuid: UUID


AvomaOperation = Annotated[
    Union[
        ListMeetings,
        GetMeeting,
        GetMeetingInsights,
        ListNotes,
        GetRecording,
        ListTranscriptions,
        GetTranscription,
        ListUsers,
        GetUser,
        ListSmartCategories,
        GetSmartCategory,
        ListTemplates,
        GetTemplate,
        ListMeetingTypes,
        GetMeetingType,
        CreateMeetingType,
        UpdateMeetingType,
        DeleteMeetingType,
        ListMeetingOutcomes,
        GetMeetingOutcome,
        CreateMeetingOutcome,
        UpdateMeetingOutcome,
        DeleteMeetingOutcome,
    ],
    Field(discriminator="operation"),
]


class AvomaConfig(NodeConfig[AvomaOperation, AvomaAPIKey]):
    pass


ROUTES = {
    "list_meetings": ("GET", "/v1/meetings/"),
    "get_meeting": ("GET", "/v1/meetings/{uuid}/"),
    "get_meeting_insights": ("GET", "/v1/meetings/{meeting_uuid}/insights/"),
    "list_notes": ("GET", "/v1/notes/"),
    "get_recording": ("GET", "/v1/recordings/"),
    "list_transcriptions": ("GET", "/v1/transcriptions/"),
    "get_transcription": ("GET", "/v1/transcriptions/{uuid}/"),
    "list_users": ("GET", "/v1/users/"),
    "get_user": ("GET", "/v1/users/{uuid}/"),
    "list_smart_categories": ("GET", "/v1/smart_categories/"),
    "get_smart_category": ("GET", "/v1/smart_categories/{uuid}/"),
    "list_templates": ("GET", "/v1/template/"),
    "get_template": ("GET", "/v1/template/{uuid}/"),
    "list_meeting_types": ("GET", "/v1/meeting_type/"),
    "get_meeting_type": ("GET", "/v1/meeting_type/{uuid}/"),
    "create_meeting_type": ("POST", "/v1/meeting_type/"),
    "update_meeting_type": ("PATCH", "/v1/meeting_type/{uuid}/"),
    "delete_meeting_type": ("DELETE", "/v1/meeting_type/{uuid}/"),
    "list_meeting_outcomes": ("GET", "/v1/meeting_outcome/"),
    "get_meeting_outcome": ("GET", "/v1/meeting_outcome/{uuid}/"),
    "create_meeting_outcome": ("POST", "/v1/meeting_outcome/"),
    "update_meeting_outcome": ("PATCH", "/v1/meeting_outcome/{uuid}/"),
    "delete_meeting_outcome": ("DELETE", "/v1/meeting_outcome/{uuid}/"),
}


class AvomaNode(WorkflowNode):
    integration_type = "automation-avoma"
    connection_evidence = ConnectionEvidence(noun="users", operation="list_users", label_keys=("label", "uuid"))

    @classmethod
    def get_config_model(cls):
        return AvomaConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an Avoma API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        for name in ("uuid", "meeting_uuid"):
            if "{" + name + "}" in path:
                path = path.replace("{" + name + "}", values.pop(name))
        kwargs = {"params": values} if method == "GET" else {"json": values} if method in {"POST", "PATCH"} else {}
        token = self.config.credentials.api_key
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        except httpx.HTTPError:
            raise ValueError("Avoma request could not be completed; inspect the resource before retrying a write") from None
        if not response.is_success:
            try:
                body = response.json()
                message = body.get("detail") if isinstance(body, dict) else None
            except ValueError:
                message = None
            return {"status": "error", "http_status": response.status_code,
                    "error": (str(message) if message else "Avoma rejected the request").replace(token, "[redacted]")}
        if response.status_code == 204:
            return {"status": "success", "http_status": 204, "data": None}
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Avoma returned a non-JSON response") from None
        if not isinstance(body, (dict, list)) or isinstance(body, dict) and ("error" in body or "detail" in body):
            raise ValueError("Avoma returned an unexpected response")
        # Preserve the provider's response and pagination, including signed media
        # links. No secondary requests/downloads and no implicit write retries.
        output = {"status": "success", "http_status": response.status_code, "data": body}
        if config.operation == "list_users":
            if not isinstance(body, list):
                raise ValueError("Avoma returned an unexpected user list")
            items = []
            for row in body:
                if not isinstance(row, dict) or not isinstance(row.get("user"), dict):
                    raise ValueError("Avoma returned an unexpected user record")
                user = row["user"]
                label = user.get("email") or " ".join(str(user.get(k) or "") for k in ("first_name", "last_name")).strip() or row.get("uuid")
                items.append({**row, "label": label})
            output["items"] = items
        return output
