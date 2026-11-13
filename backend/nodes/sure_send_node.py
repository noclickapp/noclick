"""Sure Send CRM Partner API v1, using a manually supplied API token.

Each operation issues one documented request. Lists return one provider page;
message creation sends only when the user explicitly sets send=True.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.suresend.ai"
CREDENTIAL_TYPE = "sure_send_api_token"


class SureSendAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Sure Send API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.suresend.ai",
            "x-credential-instructions": "In your Sure Send CRM dashboard, open Settings > API Tokens. Create or copy an API token with access to the records you want to automate, then paste it here without the Bearer prefix. NoClick verifies it with the current account identity endpoint.",
        })
    credential_type: Literal["sure_send_api_token"] = Field("sure_send_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without the Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def nonempty_update(self):
        if getattr(self, "operation", "").startswith("update_"):
            changed = self.model_dump(exclude_none=True, exclude={"operation", "id", "mergeTags", "mergeEmails", "mergePhones", "mergeAddresses"})
            if not changed:
                raise ValueError("Provide at least one field to update")
        return self


class _Page(_Input):
    page: int = Field(1, ge=1, le=1000000, description="One page only. Increment page to continue; meta describes pagination.")
    limit: int = Field(25, ge=1, le=100)


class EmailAddress(_Input):
    value: EmailStr = Field(..., max_length=320)
    type: Literal["work", "home", "other"] = "work"
    status: Literal["active", "bounced", "unsubscribed"] = "active"
    isPrimary: StrictBool = True


class PhoneNumber(_Input):
    value: str = Field(..., min_length=1, max_length=100)
    type: Literal["mobile", "work", "home", "other"] = "mobile"
    status: Literal["active", "disconnected", "do-not-call"] = "active"
    isPrimary: StrictBool = True


class GetIdentity(_Input):
    """Get identity."""
    operation: Literal["get_identity"] = Field("get_identity", json_schema_extra={"ui:hidden": True})


class ListPeople(_Page):
    """List people."""
    operation: Literal["list_people"] = Field("list_people", json_schema_extra={"ui:hidden": True})
    email: str | None = Field(None, max_length=100000)
    phone: str | None = Field(None, max_length=100000)
    name: str | None = Field(None, max_length=100000)
    tags: str | None = Field(None, max_length=100000)
    assignedUserId: UUID | None = None
    stageId: UUID | None = None


class GetPerson(_Input):
    """Get person."""
    operation: Literal["get_person"] = Field("get_person", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Record ID")


class CreatePerson(_Input):
    """Create person."""
    operation: Literal["create_person"] = Field("create_person", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    firstName: str | None = Field(None, max_length=100000)
    lastName: str | None = Field(None, max_length=100000)
    companyName: str | None = Field(None, max_length=100000)
    stage: str | None = Field(None, max_length=100000)
    assignedUserId: UUID | None = None
    emails: list[EmailAddress] | None = Field(None, max_length=50)
    phones: list[PhoneNumber] | None = Field(None, max_length=50)
    tags: list[str] | None = Field(None, max_length=50)
    source: str | None = Field(None, max_length=100000)


class UpdatePerson(_Input):
    """Update supplied fields; collections merge by default to preserve existing contact data."""
    operation: Literal["update_person"] = Field("update_person", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Record ID")
    firstName: str | None = Field(None, max_length=100000)
    lastName: str | None = Field(None, max_length=100000)
    companyName: str | None = Field(None, max_length=100000)
    stage: str | None = Field(None, max_length=100000)
    assignedUserId: UUID | None = None
    emails: list[EmailAddress] | None = Field(None, max_length=50)
    phones: list[PhoneNumber] | None = Field(None, max_length=50)
    tags: list[str] | None = Field(None, max_length=50)
    mergeTags: StrictBool = Field(True, description="Merge provided values with existing values; false replaces them.")
    mergeEmails: StrictBool = Field(True, description="Merge provided values with existing values; false replaces them.")
    mergePhones: StrictBool = Field(True, description="Merge provided values with existing values; false replaces them.")


class ApplyPersonTags(_Input):
    """Apply person tags."""
    operation: Literal["apply_person_tags"] = Field("apply_person_tags", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Record ID")
    tags: list[str] = Field(..., min_length=1, max_length=50)


class RemovePersonTags(_Input):
    """Remove person tags."""
    operation: Literal["remove_person_tags"] = Field("remove_person_tags", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Record ID")
    tags: list[str] = Field(..., min_length=1, max_length=50)


class ListTags(_Page):
    """List tags."""
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, max_length=100000)


class CreateTag(_Input):
    """Create tag."""
    operation: Literal["create_tag"] = Field("create_tag", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class ListNotes(_Page):
    """List notes."""
    operation: Literal["list_notes"] = Field("list_notes", json_schema_extra={"ui:hidden": True})
    personId: UUID | None = None


class GetNote(_Input):
    """Get note."""
    operation: Literal["get_note"] = Field("get_note", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Record ID")


class CreateNote(_Input):
    """Create note."""
    operation: Literal["create_note"] = Field("create_note", json_schema_extra={"ui:hidden": True})
    personId: UUID = Field(..., title="Person ID")
    subject: str | None = Field(None, max_length=100000)
    body: str = Field(..., min_length=1, max_length=100000)
    isHtml: StrictBool = False
    isPinned: StrictBool = False


class UpdateNote(_Input):
    """Update note."""
    operation: Literal["update_note"] = Field("update_note", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Record ID")
    subject: str | None = Field(None, max_length=100000)
    body: str | None = Field(None, max_length=100000)
    isHtml: StrictBool | None = None
    isPinned: StrictBool | None = None


class ListTasks(_Page):
    """List tasks."""
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"ui:hidden": True})
    personId: UUID | None = None


class GetTask(_Input):
    """Get task."""
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Record ID")


class CreateTask(_Input):
    """Create task."""
    operation: Literal["create_task"] = Field("create_task", json_schema_extra={"ui:hidden": True})
    personId: UUID = Field(..., title="Person ID")
    name: str = Field(..., min_length=1, max_length=1000)
    description: str | None = Field(None, max_length=100000)
    type: str | None = Field(None, max_length=100000)
    assignedUserId: UUID | None = None
    isCompleted: StrictBool | None = None
    dueDateTime: AwareDatetime | None = None


class UpdateTask(_Input):
    """Update task."""
    operation: Literal["update_task"] = Field("update_task", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Record ID")
    name: str | None = Field(None, max_length=100000)
    description: str | None = Field(None, max_length=100000)
    type: str | None = Field(None, max_length=100000)
    assignedUserId: UUID | None = None
    isCompleted: StrictBool | None = None
    dueDateTime: AwareDatetime | None = None


class ListAppointments(_Page):
    """List appointments."""
    operation: Literal["list_appointments"] = Field("list_appointments", json_schema_extra={"ui:hidden": True})
    personId: UUID | None = None
    userId: UUID | None = None
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None


class CreateAppointment(_Input):
    """Create appointment."""
    operation: Literal["create_appointment"] = Field("create_appointment", json_schema_extra={"ui:hidden": True})
    personId: UUID = Field(..., title="Person ID")
    title: str = Field(..., min_length=1, max_length=1000)
    startsAt: AwareDatetime
    endsAt: AwareDatetime | None = None
    userId: UUID | None = None
    description: str | None = Field(None, max_length=100000)
    location: str | None = Field(None, max_length=100000)


class ListAutomations(_Page):
    """List automations."""
    operation: Literal["list_automations"] = Field("list_automations", json_schema_extra={"ui:hidden": True})
    status: Literal["draft", "active", "inactive"] | None = None


class EnrollInAutomation(_Input):
    """Enroll in automation."""
    operation: Literal["enroll_in_automation"] = Field("enroll_in_automation", json_schema_extra={"ui:hidden": True})
    automation_id: UUID
    personId: UUID = Field(..., title="Person ID")


class ListTextMessages(_Page):
    """List text messages."""
    operation: Literal["list_text_messages"] = Field("list_text_messages", json_schema_extra={"ui:hidden": True})
    personId: UUID | None = None


class CreateTextMessage(_Input):
    """Create a message record, optionally send it. Provider acceptance does not prove delivery."""
    operation: Literal["create_text_message"] = Field("create_text_message", json_schema_extra={"ui:hidden": True})
    personId: UUID = Field(..., title="Person ID")
    body: str = Field(..., min_length=1, max_length=100000)
    toNumber: str | None = Field(None, max_length=100000)
    fromNumber: str | None = Field(None, max_length=100000)
    send: StrictBool = Field(False, description="True sends a message through Sure Send. False only records it in the CRM; no delivery is requested.")
    smsProviderId: UUID | None = None


class ListEmailMessages(_Page):
    """List email messages."""
    operation: Literal["list_email_messages"] = Field("list_email_messages", json_schema_extra={"ui:hidden": True})
    personId: UUID | None = None


class CreateEmailMessage(_Input):
    """Create a message record, optionally send it. Provider acceptance does not prove delivery."""
    operation: Literal["create_email_message"] = Field("create_email_message", json_schema_extra={"ui:hidden": True})
    personId: UUID = Field(..., title="Person ID")
    body: str = Field(..., min_length=1, max_length=100000)
    subject: str = Field(..., min_length=1, max_length=1000)
    toEmail: EmailStr | None = Field(None, max_length=100000)
    fromEmail: EmailStr | None = Field(None, max_length=100000)
    send: StrictBool = Field(False, description="True sends a message through Sure Send. False only records it in the CRM; no delivery is requested.")
    emailProviderId: UUID | None = None


# Sure Send's own MCP server: agents get its tools through a person's Sure Send sign-in.
SureSendMcpCredential = mcp_credential("sure_send", "https://suresend.ai/mcp", app="Sure Send")
SureSendCredential = Union[SureSendAPITokenCredential, SureSendMcpCredential]


SureSendOperation = Annotated[Union[
    GetIdentity,
    ListPeople,
    GetPerson,
    CreatePerson,
    UpdatePerson,
    ApplyPersonTags,
    RemovePersonTags,
    ListTags,
    CreateTag,
    ListNotes,
    GetNote,
    CreateNote,
    UpdateNote,
    ListTasks,
    GetTask,
    CreateTask,
    UpdateTask,
    ListAppointments,
    CreateAppointment,
    ListAutomations,
    EnrollInAutomation,
    ListTextMessages,
    CreateTextMessage,
    ListEmailMessages,
    CreateEmailMessage
], Field(discriminator="operation")]


class SureSendFullConfig(NodeConfig[SureSendOperation, SureSendCredential]):
    pass


# Each entry is exactly one operation in the pinned Partner API v1 contract.
REQUESTS = {
    "get_identity": ('GET', '/api/partner/identity', (), (), None),
    "list_people": ('GET', '/api/partner/people', ('page', 'limit', 'email', 'phone', 'name', 'tags', 'assignedUserId', 'stageId'), (), None),
    "get_person": ('GET', '/api/partner/people/{id}', (), (), None),
    "create_person": ('POST', '/api/partner/people', (), ('name', 'firstName', 'lastName', 'companyName', 'stage', 'assignedUserId', 'emails', 'phones', 'tags', 'source'), None),
    "update_person": ('PUT', '/api/partner/people/{id}', ('mergeTags', 'mergeEmails', 'mergePhones'), ('firstName', 'lastName', 'companyName', 'stage', 'assignedUserId', 'emails', 'phones', 'tags'), None),
    "apply_person_tags": ('POST', '/api/partner/people/{id}/tags/apply', (), ('tags',), None),
    "remove_person_tags": ('POST', '/api/partner/people/{id}/tags/delete', (), ('tags',), None),
    "list_tags": ('GET', '/api/partner/tags', ('page', 'limit', 'search'), (), None),
    "create_tag": ('POST', '/api/partner/tags', (), ('name', 'color'), 'tag'),
    "list_notes": ('GET', '/api/partner/notes', ('page', 'limit', 'personId'), (), None),
    "get_note": ('GET', '/api/partner/notes/{id}', (), (), None),
    "create_note": ('POST', '/api/partner/notes', (), ('personId', 'subject', 'body', 'isHtml', 'isPinned'), None),
    "update_note": ('PUT', '/api/partner/notes/{id}', (), ('subject', 'body', 'isHtml', 'isPinned'), None),
    "list_tasks": ('GET', '/api/partner/tasks', ('page', 'limit', 'personId'), (), None),
    "get_task": ('GET', '/api/partner/tasks/{id}', (), (), None),
    "create_task": ('POST', '/api/partner/tasks', (), ('personId', 'name', 'description', 'type', 'assignedUserId', 'isCompleted', 'dueDateTime'), None),
    "update_task": ('PUT', '/api/partner/tasks/{id}', (), ('name', 'description', 'type', 'assignedUserId', 'isCompleted', 'dueDateTime'), None),
    "list_appointments": ('GET', '/api/partner/appointments', ('page', 'limit', 'personId', 'userId', 'start', 'end'), (), None),
    "create_appointment": ('POST', '/api/partner/appointments', (), ('personId', 'title', 'startsAt', 'endsAt', 'userId', 'description', 'location'), None),
    "list_automations": ('GET', '/api/partner/automations', ('page', 'limit', 'status'), (), None),
    "enroll_in_automation": ('POST', '/api/partner/automations/{automation_id}/enrollments', (), ('personId',), None),
    "list_text_messages": ('GET', '/api/partner/textMessages', ('page', 'limit', 'personId'), (), None),
    "create_text_message": ('POST', '/api/partner/textMessages', ('send', 'smsProviderId'), ('personId', 'body', 'toNumber', 'fromNumber'), None),
    "list_email_messages": ('GET', '/api/partner/emailMessages', ('page', 'limit', 'personId'), (), None),
    "create_email_message": ('POST', '/api/partner/emailMessages', ('send', 'emailProviderId'), ('personId', 'body', 'subject', 'toEmail', 'fromEmail'), None),
}


class SureSendNode(WorkflowNode):
    integration_type = "automation-sure-send"
    credential_provider_labels = {"sure_send": "Sure Send Account"}
    connection_evidence = ConnectionEvidence(noun="Sure Send account", identity_operation="get_identity")

    @classmethod
    def get_config_model(cls):
        return SureSendFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Sure Send API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, path, query_fields, body_fields, wrapper = REQUESTS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        for key in ("id", "automation_id"):
            if key in values:
                path = path.replace("{" + key + "}", values[key])
        params = {key: (str(values[key]).lower() if isinstance(values[key], bool) else values[key])
                  for key in query_fields if key in values}
        body = {key: values[key] for key in body_fields if key in values}
        if wrapper:
            body = {wrapper: body}
        request_kwargs = {"params": params}
        if method != "GET":
            request_kwargs["json"] = body
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **request_kwargs)
        if not 200 <= response.status_code < 300:
            try:
                error_body = response.json()
                error = error_body.get("errorMessage") or error_body.get("message") or error_body.get("error")
            except (ValueError, AttributeError):
                error = None
            if not isinstance(error, str):
                error = "Sure Send returned HTTP " + str(response.status_code)
            return {"status": "error", "http_status": response.status_code, "error": error[:4000].replace(token, "[redacted]")}
        data = response.json() if response.content else None
        if isinstance(data, dict) and (data.get("errorMessage") or data.get("error") or data.get("errors")):
            raise ValueError("Sure Send returned an error envelope")
        result = {"status": "success", "operation": op.operation, "data": data, "http_status": response.status_code}
        if op.operation == "get_identity":
            if not isinstance(data, dict) or not isinstance(data.get("account"), dict) or not data["account"].get("name"):
                raise ValueError("Sure Send identity response is missing the account")
            result["name"] = data["account"]["name"]
        if op.operation.startswith("list_"):
            # Preserve the provider envelope, including meta. Never imply all pages were fetched.
            result["page"] = op.page
        if op.operation in {"create_text_message", "create_email_message"}:
            result["send_requested"] = op.send
            result["delivery_verified"] = False
        return result
