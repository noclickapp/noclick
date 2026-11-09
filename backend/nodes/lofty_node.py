"""Lofty CRM operations using a user-scoped personal API key.

Contract: https://developer.lofty.com/openapi/openapi.json (1.0).
API-key wire authentication: https://developer.lofty.com/authentication/api-keys.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class LoftyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Lofty API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.lofty.com/authentication/api-keys",
            "x-credential-instructions": "In Lofty, open Settings → Integrations → API and create a personal API key with the VIEW, ADD, EDIT, DEL or RUN permissions needed for your operations. Paste only the key, without the token prefix. NoClick verifies your current-user profile on connect.",
        })
    credential_type: Literal["lofty_api_key"] = Field("lofty_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=8192,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _LeadFields(_Input):
    firstName: str | None = Field(None, min_length=1, max_length=30, title="First name")
    lastName: str | None = Field(None, max_length=30, title="Last name")
    emails: list[str] | None = Field(None, title="Email addresses")
    phones: list[str] | None = Field(None, title="Phone numbers")
    leadTypes: list[Literal[-1, 1, 2, 5, 6, 7, 8, 9]] | None = Field(None, title="Lead types", description="Other -1, Seller 1, Buyer 2, Renter 5, Investor 6, Agent 7, Homeowner 8, Landlord 9.")
    assignedUserId: int | None = Field(None, ge=1, title="Assigned user ID")
    stage: str | None = Field(None, max_length=19)
    source: str | None = None
    tags: list[str] | None = Field(None, description="Replace all existing tags; omit to preserve them.")
    tagsAdd: list[str] | None = Field(None, title="Tags to add", description="Append tags while retaining existing tags.")
    segments: list[str] | None = None
    cannotText: bool | None = Field(None, title="Cannot text")
    cannotCall: bool | None = Field(None, title="Cannot call")
    cannotEmail: bool | None = Field(None, title="Cannot email")


class _LeadID(_Input):
    leadId: int = Field(..., ge=1, title="Lead ID")


class _NoteFields(_LeadID):
    content: str = Field(..., min_length=1, max_length=2000)
    isPin: bool = Field(False, title="Pin note")

    @field_validator("content")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Note content must not be blank")
        return value


class _NoteID(_Input):
    noteId: int = Field(..., ge=1, title="Note ID")


class _TaskID(_Input):
    taskId: int = Field(..., ge=1, title="Task ID")


class _TaskFields(_Input):
    content: str | None = None
    startAt: str | None = Field(None, title="Start time", description="ISO8601 timestamp with timezone offset.")
    endAt: str | None = Field(None, title="End time", description="ISO8601 timestamp with timezone offset; task deadline.")
    timeZoneCode: str | None = Field(None, title="Timezone", description="IANA timezone, for example America/Los_Angeles.")
    address: str | None = None

    @field_validator("startAt", "endAt")
    @classmethod
    def timestamp(cls, value):
        if value is not None and datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("Use an ISO8601 timestamp with timezone offset")
        return value


class LoftyGetProfile(_Input):
    """Read the profile of the user whose key is connected."""
    operation: Literal["get_profile"] = Field("get_profile", json_schema_extra={"ui:hidden": True})



class LoftyListLeads(_Input):
    """Read one page of leads; use offset or the returned scrollId for the next page."""
    operation: Literal["list_leads"] = Field("list_leads", json_schema_extra={"ui:hidden": True})
    offset: int = Field(0, ge=0)
    limit: int = Field(25, ge=1, le=100)
    scrollId: str | None = Field(None, title="Scroll ID")
    stage: str | None = None
    source: str | None = None
    email: str | None = None
    phone: str | None = None
    assignedUserId: int | None = Field(None, ge=1, title="Assigned user ID")
    contacted: bool | None = None
    allTags: str | None = Field(None, title="All tags", description="Comma-separated tag names (AND).")
    anyTags: str | None = Field(None, title="Any tags", description="Comma-separated tag names (OR).")


class LoftyGetLead(_LeadID):
    """Read a lead by its ID."""
    operation: Literal["get_lead"] = Field("get_lead", json_schema_extra={"ui:hidden": True})
    withTrash: bool = Field(False, title="Include trashed lead")


class LoftyCreateLead(_LeadFields):
    """Create a lead; omitted assignee uses Lofty routing and omitted ownership defaults to the caller."""
    operation: Literal["create_lead"] = Field("create_lead", json_schema_extra={"ui:hidden": True})
    firstName: str = Field(..., min_length=1, max_length=30, title="First name")


class LoftyUpdateLead(_LeadFields):
    """Update supplied lead fields; omitted fields remain unchanged."""
    operation: Literal["update_lead"] = Field("update_lead", json_schema_extra={"ui:hidden": True})
    leadId: int = Field(..., ge=1, title="Lead ID")

    @model_validator(mode="after")
    def changes(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "leadId"}):
            raise ValueError("Supply at least one lead field to update")
        return self


class LoftyDeleteLead(_LeadID):
    """Move a lead to trash."""
    operation: Literal["delete_lead"] = Field("delete_lead", json_schema_extra={"ui:hidden": True})
    reason: str = Field(..., min_length=1, description="Reason for moving the lead to trash.")



class LoftyListNotes(_LeadID):
    """List notes on a lead."""
    operation: Literal["list_notes"] = Field("list_notes", json_schema_extra={"ui:hidden": True})
    includeSystemNote: bool = Field(False, title="Include system notes")


class LoftyGetNote(_NoteID):
    """Read a note by its ID."""
    operation: Literal["get_note"] = Field("get_note", json_schema_extra={"ui:hidden": True})



class LoftyCreateNote(_NoteFields):
    """Add a note to a lead; returns the note ID, whose read may be briefly delayed."""
    operation: Literal["create_note"] = Field("create_note", json_schema_extra={"ui:hidden": True})



class LoftyUpdateNote(_NoteFields):
    """Update a note on the specified lead."""
    operation: Literal["update_note"] = Field("update_note", json_schema_extra={"ui:hidden": True})
    noteId: int = Field(..., ge=1, title="Note ID")


class LoftyDeleteNote(_NoteID):
    """Delete a note."""
    operation: Literal["delete_note"] = Field("delete_note", json_schema_extra={"ui:hidden": True})



class LoftyListTasks(_LeadID):
    """List all tasks and appointments on a lead."""
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"ui:hidden": True})



class LoftyGetTask(_TaskID):
    """Read a task or appointment."""
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"ui:hidden": True})



class LoftyCreateTask(_TaskFields):
    """Create a follow-up task or appointment on a lead."""
    operation: Literal["create_task"] = Field("create_task", json_schema_extra={"ui:hidden": True})
    leadId: int = Field(..., ge=1, title="Lead ID")
    type: Literal["Other", "Call", "Email", "Text", "Appointment"] = Field(..., title="Task type")
    content: str = Field(..., min_length=1)
    assignedRole: Literal["Agent", "Assistant"] = Field(..., title="Assigned role")
    endAt: str = Field(..., title="End time", description="ISO8601 timestamp with timezone offset; task deadline.")


class LoftyUpdateTask(_TaskFields):
    """Update supplied task fields; use finish or unfinish to change completion."""
    operation: Literal["update_task"] = Field("update_task", json_schema_extra={"ui:hidden": True})
    taskId: int = Field(..., ge=1, title="Task ID")

    @model_validator(mode="after")
    def changes(self):
        if not any(getattr(self, key) is not None for key in ("content", "startAt", "endAt", "address")):
            raise ValueError("Supply content, start time, end time or address")
        return self


class LoftyDeleteTask(_TaskID):
    """Delete a task or appointment."""
    operation: Literal["delete_task"] = Field("delete_task", json_schema_extra={"ui:hidden": True})



class LoftyFinishTask(_TaskID):
    """Mark a task completed; smart-plan tasks cannot be finished through this API."""
    operation: Literal["finish_task"] = Field("finish_task", json_schema_extra={"ui:hidden": True})



class LoftyUnfinishTask(_TaskID):
    """Reopen a completed task."""
    operation: Literal["unfinish_task"] = Field("unfinish_task", json_schema_extra={"ui:hidden": True})



class LoftySendEmail(_LeadID):
    """Send an email using the connected user’s outgoing email configuration."""
    operation: Literal["send_email"] = Field("send_email", json_schema_extra={"ui:hidden": True})
    subject: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    toEmail: str | None = Field(None, title="Recipient email", description="Selects an email on the lead; otherwise Lofty uses the primary email.")


class LoftySendSMS(_LeadID):
    """Send an SMS from the connected user’s active virtual number."""
    operation: Literal["send_sms"] = Field("send_sms", json_schema_extra={"ui:hidden": True})
    content: str = Field(..., min_length=1)
    phoneNumber: str | None = Field(None, title="Phone number")
    phoneCode: str | None = Field(None, title="Phone country code")


class LoftyListTags(_Input):
    """List lead tags visible to the caller."""
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})



class LoftyListMembers(_Input):
    """Read one page of team members."""
    operation: Literal["list_members"] = Field("list_members", json_schema_extra={"ui:hidden": True})
    offset: int = Field(0, ge=0)
    limit: int = Field(25, ge=1, le=100)


LoftyConfig = Annotated[Union[
    LoftyGetProfile,
    LoftyListLeads,
    LoftyGetLead,
    LoftyCreateLead,
    LoftyUpdateLead,
    LoftyDeleteLead,
    LoftyListNotes,
    LoftyGetNote,
    LoftyCreateNote,
    LoftyUpdateNote,
    LoftyDeleteNote,
    LoftyListTasks,
    LoftyGetTask,
    LoftyCreateTask,
    LoftyUpdateTask,
    LoftyDeleteTask,
    LoftyFinishTask,
    LoftyUnfinishTask,
    LoftySendEmail,
    LoftySendSMS,
    LoftyListTags,
    LoftyListMembers
], Field(discriminator="operation")]


class LoftyFullConfig(NodeConfig[LoftyConfig, LoftyAPIKeyCredential]):
    pass


ROUTES = {
    'get_profile': ('GET', '/v1.0/me'),
    'list_leads': ('GET', '/v1.0/leads'),
    'create_lead': ('POST', '/v1.0/leads'),
    'get_lead': ('GET', '/v1.0/leads/{leadId}'),
    'update_lead': ('PUT', '/v1.0/leads/{leadId}'),
    'delete_lead': ('DELETE', '/v1.0/leads/{leadId}'),
    'list_notes': ('GET', '/v1.0/notes'),
    'create_note': ('POST', '/v1.0/notes'),
    'get_note': ('GET', '/v1.0/notes/{noteId}'),
    'update_note': ('PUT', '/v1.0/notes/{noteId}'),
    'delete_note': ('DELETE', '/v1.0/notes/{noteId}'),
    'list_tasks': ('GET', '/v2.0/tasks'),
    'create_task': ('POST', '/v2.0/tasks'),
    'get_task': ('GET', '/v2.0/tasks/{taskId}'),
    'update_task': ('PUT', '/v2.0/tasks/{taskId}'),
    'delete_task': ('DELETE', '/v2.0/tasks/{taskId}'),
    'finish_task': ('POST', '/v2.0/tasks/{taskId}/finish'),
    'unfinish_task': ('POST', '/v2.0/tasks/{taskId}/unfinish'),
    'send_email': ('POST', '/v1.0/message/email/send'),
    'send_sms': ('POST', '/v1.0/message/sms/send'),
    'list_tags': ('GET', '/v1.0/teamFeatures/listTag'),
    'list_members': ('GET', '/v1.0/members'),
}


class LoftyNode(WorkflowNode):
    integration_type = "automation-lofty"
    connection_evidence = ConnectionEvidence(noun="Lofty account", identity_operation="get_profile")

    @classmethod
    def get_config_model(cls):
        return LoftyFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Lofty API key")
        op = self.config.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for field in ("leadId", "noteId", "taskId"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", str(values.pop(field)))
        kwargs = {}
        if method in {"GET", "DELETE"}:
            kwargs["params"] = {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
        elif values:
            kwargs["json"] = values
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.lofty.com" + path,
                headers={"Authorization": "token " + self.config.credentials.api_key,
                    "Content-Type": "application/json", "Accept": "application/json", "X-Error-Status": "true"},
                **kwargs)
        if not response.is_success:
            # Preserve provider rejection text for manual credential verification.
            message = response.text.replace(self.config.credentials.api_key, "[redacted]")[:2000]
            return {"status": "error", "http_status": response.status_code, "error": message}
        if op.operation in {"delete_lead", "update_note", "delete_note"} and not response.content:
            return {"status": "success", "data": None}
        body = response.json()
        if not isinstance(body, (dict, list)):
            raise ValueError("Expected Lofty JSON object or list")
        if isinstance(body, dict) and body.get("success") is False:
            return {"status": "error", "error": "Lofty reported success=false", "data": body}
        result = {"status": "success", "data": body}
        if op.operation == "get_profile":
            if not isinstance(body, dict) or not (body.get("memberUserId") or body.get("id")):
                raise ValueError("Lofty returned no current-user identity")
            result["name"] = " ".join(str(body[k]) for k in ("firstName", "lastName") if body.get(k)) or body.get("email") or str(body.get("memberUserId") or body["id"])
        return result
