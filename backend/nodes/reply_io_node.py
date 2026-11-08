"""Reply API v3 contacts, lists, sequences and tasks.

Contract: https://docs.reply.io/api-reference/bundled.yaml (3.0.0).
Each operation issues one documented request; pagination is explicit.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.reply.io"


class ReplyIoAPIKey(BaseModel):
    model_config = ConfigDict(title="Reply Io API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.reply.io/api-reference/introduction",
            "x-credential-instructions": "Copy your API key from Reply Settings → API Key. Paste only the key. Enable contacts:read, contacts:write, contacts:operate, sequences:read, sequences:write, sequences:operate, tasks:read, tasks:write and tasks:operate for the operations you use. Connecting checks your current user; it does not verify every permission.",
        })
    credential_type: Literal["reply_io_api_key"] = Field("reply_io_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste only the API key without the Bearer prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Page(Input):
    top: int = Field(25, ge=1, le=1000, description="Page size. Use skip to fetch the next page when hasMore is true.")
    skip: int = Field(0, ge=0, description="Number of results to skip.")


class GetCurrentUser(Input):
    operation: Literal["get_current_user"] = "get_current_user"


class ListContacts(Page):
    operation: Literal["list_contacts"] = "list_contacts"
    email: EmailStr | None = None
    linkedIn: AnyHttpUrl | None = Field(None, title="LinkedIn URL")


class ContactFields(Input):
    email: EmailStr | None = None
    firstName: str | None = Field(None, title="First name")
    lastName: str | None = Field(None, title="Last name")
    phone: str | None = None
    title: str | None = Field(None, title="Job title")
    company: str | None = None
    linkedInUrl: AnyHttpUrl | None = Field(None, title="LinkedIn URL")
    notes: str | None = None


class CreateContact(ContactFields):
    operation: Literal["create_contact"] = "create_contact"

    @model_validator(mode="after")
    def identity(self):
        if not self.email and not self.linkedInUrl:
            raise ValueError("Supply an email or LinkedIn URL")
        return self


class ContactId(Input):
    contact_id: int = Field(..., ge=1, title="Contact ID")


class GetContact(ContactId):
    operation: Literal["get_contact"] = "get_contact"


class UpdateContact(ContactFields, ContactId):
    operation: Literal["update_contact"] = "update_contact"
    isOptedOut: bool | None = Field(None, title="Opted out")
    stage: str | None = None

    @model_validator(mode="after")
    def changes(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "contact_id"}):
            raise ValueError("Supply at least one contact field to update")
        return self


class DeleteContact(ContactId):
    operation: Literal["delete_contact"] = "delete_contact"


class ListContactLists(Page):
    operation: Literal["list_contact_lists"] = "list_contact_lists"
    search: str | None = None


class CreateContactList(Input):
    operation: Literal["create_contact_list"] = "create_contact_list"
    name: str = Field(..., min_length=1)
    isShared: bool = Field(False, title="Share with team")


class ListId(Input):
    list_id: int = Field(..., ge=1, title="Contact list ID")


class GetContactList(ListId):
    operation: Literal["get_contact_list"] = "get_contact_list"


class UpdateContactList(ListId):
    operation: Literal["update_contact_list"] = "update_contact_list"
    name: str = Field(..., min_length=1)


class DeleteContactList(ListId):
    operation: Literal["delete_contact_list"] = "delete_contact_list"


ContactIds = Annotated[list[Annotated[int, Field(ge=1)]], Field(min_length=1, max_length=1000)]


class AddContactsToList(ListId):
    operation: Literal["add_contacts_to_list"] = "add_contacts_to_list"
    contactIds: ContactIds = Field(..., title="Contact IDs")


class ListSequences(Page):
    operation: Literal["list_sequences"] = "list_sequences"
    name: str | None = None
    status: Literal["active", "paused", "new"] | None = None
    isArchived: bool | None = Field(None, title="Archived")


class SequenceId(Input):
    sequence_id: int = Field(..., ge=1, title="Sequence ID")


class GetSequence(SequenceId):
    operation: Literal["get_sequence"] = "get_sequence"


class UpdateSequence(SequenceId):
    operation: Literal["update_sequence"] = "update_sequence"
    name: str = Field(..., min_length=1, description="Rename this sequence.")


class StartSequence(SequenceId):
    operation: Literal["start_sequence"] = "start_sequence"


class PauseSequence(SequenceId):
    operation: Literal["pause_sequence"] = "pause_sequence"


class ListSequenceContacts(SequenceId, Page):
    operation: Literal["list_sequence_contacts"] = "list_sequence_contacts"


class AddContactsToSequence(SequenceId):
    operation: Literal["add_contacts_to_sequence"] = "add_contacts_to_sequence"
    contactIds: ContactIds = Field(..., title="Contact IDs")
    removeFromExisting: bool = Field(False, title="Remove from existing sequences")
    ignoreStepDelay: bool = Field(False, title="Ignore first step delay")


class RemoveContactFromSequence(SequenceId, ContactId):
    operation: Literal["remove_contact_from_sequence"] = "remove_contact_from_sequence"


class ListTasks(Page):
    operation: Literal["list_tasks"] = "list_tasks"


class TaskId(Input):
    task_id: int = Field(..., ge=1, title="Task ID")


class GetTask(TaskId):
    operation: Literal["get_task"] = "get_task"
    includeContent: bool = Field(False, title="Include rendered content")


class TaskTemplate(Input):
    body: str = Field(..., min_length=1)
    subject: str | None = None


class CreateTask(Input):
    operation: Literal["create_task"] = "create_task"
    taskType: Literal["toDo", "call", "meeting", "linkedIn", "manualEmail", "sms", "whatsApp"] = Field(..., title="Task type")
    startAt: datetime = Field(..., title="Start time")
    dueTo: datetime = Field(..., title="Due time")
    contactId: int | None = Field(None, ge=1, title="Contact ID")
    linkedInTaskType: Literal["message", "connect", "inMail", "viewProfile"] | None = Field(None, title="LinkedIn action")
    template: TaskTemplate

    @model_validator(mode="after")
    def times(self):
        if self.taskType != "toDo" and self.contactId is None:
            raise ValueError("A contact ID is required for this task type")
        if self.startAt.tzinfo is None or self.dueTo.tzinfo is None:
            raise ValueError("Use times with a timezone")
        if self.startAt.year < 2015 or self.dueTo <= self.startAt:
            raise ValueError("Start must be on or after 2015 and due time must follow start")
        return self


class CompleteTask(TaskId):
    operation: Literal["complete_task"] = "complete_task"
    callResolution: Literal[0, 1, 2] | None = Field(None, title="Call resolution (0 positive, 1 to call, 2 negative)")
    finishProspectInSequence: bool = Field(False, title="Finish contact in sequence")


ReplyIoConfig = Annotated[Union[
    GetCurrentUser, ListContacts, CreateContact, GetContact, UpdateContact, DeleteContact,
    ListContactLists, CreateContactList, GetContactList, UpdateContactList, DeleteContactList, AddContactsToList,
    ListSequences, GetSequence, UpdateSequence, StartSequence, PauseSequence,
    ListSequenceContacts, AddContactsToSequence, RemoveContactFromSequence,
    ListTasks, GetTask, CreateTask, CompleteTask,
], Field(discriminator="operation")]


class ReplyIoFullConfig(NodeConfig[ReplyIoConfig, ReplyIoAPIKey]):
    pass


# Operation -> method, contract route, path parameter -> config field.
ROUTES = {
    "get_current_user": ("GET", "/v3/whoami", {}),
    "list_contacts": ("GET", "/v3/contacts", {}),
    "create_contact": ("POST", "/v3/contacts", {}),
    "get_contact": ("GET", "/v3/contacts/{id}", {"id": "contact_id"}),
    "update_contact": ("PATCH", "/v3/contacts/{id}", {"id": "contact_id"}),
    "delete_contact": ("DELETE", "/v3/contacts/{id}", {"id": "contact_id"}),
    "list_contact_lists": ("GET", "/v3/contact-lists", {}),
    "create_contact_list": ("POST", "/v3/contact-lists", {}),
    "get_contact_list": ("GET", "/v3/contact-lists/{id}", {"id": "list_id"}),
    "update_contact_list": ("PUT", "/v3/contact-lists/{id}", {"id": "list_id"}),
    "delete_contact_list": ("DELETE", "/v3/contact-lists/{id}", {"id": "list_id"}),
    "add_contacts_to_list": ("POST", "/v3/contact-lists/{id}/add-contacts", {"id": "list_id"}),
    "list_sequences": ("GET", "/v3/sequences", {}),
    "get_sequence": ("GET", "/v3/sequences/{id}", {"id": "sequence_id"}),
    "update_sequence": ("PATCH", "/v3/sequences/{id}", {"id": "sequence_id"}),
    "start_sequence": ("POST", "/v3/sequences/{id}/start", {"id": "sequence_id"}),
    "pause_sequence": ("POST", "/v3/sequences/{id}/pause", {"id": "sequence_id"}),
    "list_sequence_contacts": ("GET", "/v3/sequences/{id}/contacts", {"id": "sequence_id"}),
    "add_contacts_to_sequence": ("POST", "/v3/sequences/{id}/contact-links/bulk", {"id": "sequence_id"}),
    "remove_contact_from_sequence": ("DELETE", "/v3/sequences/{id}/contact-links/{contact_id}", {"id": "sequence_id", "contact_id": "contact_id"}),
    "list_tasks": ("GET", "/v3/tasks", {}),
    "get_task": ("GET", "/v3/tasks/{id}", {"id": "task_id"}),
    "create_task": ("POST", "/v3/tasks", {}),
    "complete_task": ("POST", "/v3/tasks/{id}/complete", {"id": "task_id"}),
}


class ReplyIoNode(WorkflowNode):
    integration_type = "automation-reply-io"
    connection_evidence = ConnectionEvidence(noun="Reply account", identity_operation="get_current_user", identity_keys=("username",))

    @classmethod
    def get_config_model(cls):
        return ReplyIoFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Reply Io API key")
        op = self.config.config
        method, route, path_fields = ROUTES[op.operation]
        path = route.format(**{param: getattr(op, field) for param, field in path_fields.items()})
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation", *path_fields.values()})
        kwargs = {}
        if method == "GET":
            kwargs["params"] = {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
        elif values:
            kwargs["json"] = values
        token = self.config.credentials.api_key
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        if response.status_code >= 300:
            message = response.text.replace(token, "[redacted]")
            raise ValueError(f"Reply API HTTP {response.status_code}: {message[:2000]}")
        data = None if response.status_code == 204 or not response.content else response.json()
        if isinstance(op, GetCurrentUser):
            if not isinstance(data, dict) or not isinstance(data.get("username"), str) or type(data.get("userId")) is not int or type(data.get("teamId")) is not int:
                raise ValueError("Reply returned an invalid current user")
        result = {"status": "success", "data": data}
        if isinstance(op, Page):
            if not isinstance(data, dict) or not isinstance(data.get("items"), list) or not isinstance(data.get("hasMore"), bool):
                raise ValueError("Reply returned an invalid page")
            result["next_skip"] = op.skip + op.top if data["hasMore"] else None
        await self.emit(result)
        return result
