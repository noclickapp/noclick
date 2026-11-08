"""Reply API v3: contacts, lists, sequences and manual tasks.

Wire contract: https://docs.reply.io/api-reference/bundled.yaml (3.0.0).
Each operation makes one request. Pagination is explicit; writes are never retried.
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

BASE = "https://api.reply.io"
CREDENTIAL_TYPE = "reply_api_key"
PositiveID = Annotated[int, Field(ge=1)]
Text = Annotated[str, Field(min_length=1, max_length=10000)]


class ReplyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Reply API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.reply.io/api-reference/authentication",
            "x-credential-instructions": "In Reply, open Settings → API Key and copy your API key. Paste the key alone. NoClick sends it as a Bearer token to api.reply.io and reads your contact lists to check the connection.",
        })
    credential_type: Literal["reply_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", repr=False, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def valid_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key alone, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    top: int = Field(25, ge=1, le=100, description="Number of records in this page.")
    skip: int = Field(0, ge=0, description="Records to skip; use next_skip from the previous page.")


class _Contact(_Input):
    contact_id: PositiveID = Field(..., title="Contact ID")


class _Sequence(_Input):
    sequence_id: PositiveID = Field(..., title="Sequence ID")


class GetAccount(_Input):
    """Read the user and team accepting this API key."""
    operation: Literal["get_account"] = "get_account"


class ListContacts(_Page):
    """List or find contacts by email or LinkedIn profile."""
    operation: Literal["list_contacts"] = "list_contacts"
    email: str | None = None
    linkedIn: str | None = Field(None, title="LinkedIn URL")


class GetContact(_Contact):
    operation: Literal["get_contact"] = "get_contact"


class _ContactFields(_Input):
    email: str | None = None
    firstName: str | None = Field(None, title="First name")
    lastName: str | None = Field(None, title="Last name")
    phone: str | None = None
    title: str | None = Field(None, title="Job title")
    company: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    linkedInUrl: str | None = Field(None, title="LinkedIn URL")
    notes: str | None = None


class CreateContact(_ContactFields):
    operation: Literal["create_contact"] = "create_contact"

    @model_validator(mode="after")
    def identifier(self):
        if not self.email and not self.linkedInUrl:
            raise ValueError("Provide an email address or LinkedIn URL")
        return self


class UpdateContact(_ContactFields, _Contact):
    """Patch supplied contact fields; omitted fields stay unchanged."""
    operation: Literal["update_contact"] = "update_contact"
    isOptedOut: bool | None = Field(None, title="Opted out")

    @model_validator(mode="after")
    def changes(self):
        if not any(getattr(self, name) is not None for name in self.__class__.model_fields if name not in {"operation", "contact_id"}):
            raise ValueError("Provide at least one field to change")
        return self


class DeleteContact(_Contact):
    """Permanently delete a contact."""
    operation: Literal["delete_contact"] = "delete_contact"


class ListContactNotes(_Contact, _Page):
    operation: Literal["list_contact_notes"] = "list_contact_notes"


class AddContactNote(_Contact):
    operation: Literal["add_contact_note"] = "add_contact_note"
    notes: Text = Field(..., title="Note")


class ListContactLists(_Page):
    operation: Literal["list_contact_lists"] = "list_contact_lists"
    search: str | None = None


class CreateContactList(_Input):
    operation: Literal["create_contact_list"] = "create_contact_list"
    name: Text
    isShared: bool = Field(False, title="Share with team")


class AddContactsToList(_Input):
    operation: Literal["add_contacts_to_list"] = "add_contacts_to_list"
    list_id: PositiveID = Field(..., title="Contact list ID")
    contactIds: list[PositiveID] = Field(..., min_length=1, max_length=1000, title="Contact IDs")


class ListSequences(_Page):
    operation: Literal["list_sequences"] = "list_sequences"
    name: str | None = None
    status: Literal["active", "paused", "new"] | None = None
    isArchived: bool | None = Field(None, title="Archived")


class GetSequence(_Sequence):
    operation: Literal["get_sequence"] = "get_sequence"


class StartSequence(_Sequence):
    """Start sending from an existing configured sequence."""
    operation: Literal["start_sequence"] = "start_sequence"


class PauseSequence(_Sequence):
    operation: Literal["pause_sequence"] = "pause_sequence"


class ListSequenceContacts(_Sequence, _Page):
    operation: Literal["list_sequence_contacts"] = "list_sequence_contacts"


class AddContactsToSequence(_Sequence):
    """Enroll contacts. An active sequence may start outreach immediately."""
    operation: Literal["add_contacts_to_sequence"] = "add_contacts_to_sequence"
    contactIds: list[PositiveID] = Field(..., min_length=1, max_length=1000, title="Contact IDs")
    removeFromExisting: bool = Field(False, title="Remove from current sequences")
    ignoreStepDelay: bool = Field(False, title="Skip first step delay")
    startStepId: PositiveID | None = Field(None, title="Starting step ID")
    startFrom: datetime | None = Field(None, title="Start time")


class RemoveContactFromSequence(_Sequence, _Contact):
    operation: Literal["remove_contact_from_sequence"] = "remove_contact_from_sequence"


class ListTasks(_Page):
    operation: Literal["list_tasks"] = "list_tasks"


class GetTask(_Input):
    operation: Literal["get_task"] = "get_task"
    task_id: PositiveID = Field(..., title="Task ID")
    includeContent: bool = Field(False, title="Include rendered content")


class CompleteTask(_Input):
    """Mark a task complete without executing or sending its content."""
    operation: Literal["complete_task"] = "complete_task"
    task_id: PositiveID = Field(..., title="Task ID")
    callResolution: Literal[0, 1, 2] | None = Field(None, title="Call resolution", description="0 positive, 1 call again, 2 negative.")
    finishProspectInSequence: bool = Field(False, title="Also finish contact in sequence")


ReplyOperation = Annotated[Union[GetAccount, ListContacts, GetContact, CreateContact,
    UpdateContact, DeleteContact, ListContactNotes, AddContactNote, ListContactLists,
    CreateContactList, AddContactsToList, ListSequences, GetSequence, StartSequence,
    PauseSequence, ListSequenceContacts, AddContactsToSequence, RemoveContactFromSequence,
    ListTasks, GetTask, CompleteTask], Field(discriminator="operation")]


class ReplyFullConfig(NodeConfig[ReplyOperation, ReplyAPIKeyCredential]):
    pass


# One operation -> one provider endpoint. The final field is the documented success status.
ROUTES = {
    "get_account": ("GET", "/v3/whoami", 200),
    "list_contacts": ("GET", "/v3/contacts", 200),
    "get_contact": ("GET", "/v3/contacts/{contact_id}", 200),
    "create_contact": ("POST", "/v3/contacts", 201),
    "update_contact": ("PATCH", "/v3/contacts/{contact_id}", 200),
    "delete_contact": ("DELETE", "/v3/contacts/{contact_id}", 204),
    "list_contact_notes": ("GET", "/v3/contacts/{contact_id}/notes", 200),
    "add_contact_note": ("POST", "/v3/contacts/{contact_id}/notes", 204),
    "list_contact_lists": ("GET", "/v3/contact-lists", 200),
    "create_contact_list": ("POST", "/v3/contact-lists", 201),
    "add_contacts_to_list": ("POST", "/v3/contact-lists/{list_id}/add-contacts", 200),
    "list_sequences": ("GET", "/v3/sequences", 200),
    "get_sequence": ("GET", "/v3/sequences/{sequence_id}", 200),
    "start_sequence": ("POST", "/v3/sequences/{sequence_id}/start", 200),
    "pause_sequence": ("POST", "/v3/sequences/{sequence_id}/pause", 200),
    "list_sequence_contacts": ("GET", "/v3/sequences/{sequence_id}/contacts", 200),
    "add_contacts_to_sequence": ("POST", "/v3/sequences/{sequence_id}/contact-links/bulk", 200),
    "remove_contact_from_sequence": ("DELETE", "/v3/sequences/{sequence_id}/contact-links/{contact_id}", 204),
    "list_tasks": ("GET", "/v3/tasks", 200),
    "get_task": ("GET", "/v3/tasks/{task_id}", 200),
    "complete_task": ("POST", "/v3/tasks/{task_id}/complete", 200),
}
NO_BODY = {"start_sequence", "pause_sequence"}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class ReplyNode(WorkflowNode):
    integration_type = "automation-reply"
    connection_evidence = ConnectionEvidence(noun="contact lists", operation="list_contact_lists",
        identity_operation="get_account", label_keys=("name", "id"), identity_keys=("username",))

    @classmethod
    def get_config_model(cls):
        return ReplyFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Attach a Reply API key")
        config = self.config.config
        secret = self.config.credentials.api_key
        method, template, expected = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        path = template.format(**values)
        payload = {k: v for k, v in values.items() if k != "operation" and "{" + k + "}" not in template}
        params = payload if method == "GET" else None
        if params is not None:
            params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        kwargs = {"params": params} if method == "GET" else {}
        if method in {"POST", "PATCH"} and config.operation not in NO_BODY:
            kwargs["json"] = payload
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"Authorization": "Bearer " + secret, "Accept": "application/json"}, **kwargs)
        except httpx.HTTPError:
            return {"status": "error", "error": "Reply request could not be confirmed; inspect writes before retrying."}
        if response.status_code != expected:
            message = "Reply returned HTTP " + str(response.status_code)
            try:
                problem = response.json()
                if isinstance(problem, dict):
                    message = problem.get("detail") or problem.get("title") or message
            except ValueError:
                pass
            return _redact({"status": "error", "http_status": response.status_code,
                "error": str(message), "retry_after": response.headers.get("Retry-After")}, secret)
        out = {"status": "success", "operation": config.operation, "http_status": response.status_code}
        if expected == 204:
            return {**out, "acknowledged": True}
        try:
            body = response.json()
        except ValueError:
            return {"status": "error", "error": "Reply returned an unexpected non-JSON response; inspect writes before retrying."}
        if not isinstance(body, dict):
            return {"status": "error", "error": "Reply returned an unexpected response shape."}
        if isinstance(body.get("status"), int) and body["status"] >= 400 or body.get("error") or body.get("errors"):
            return _redact({"status": "error", "error": str(body.get("detail") or body.get("error") or "Reply returned an error response.")}, secret)
        if config.operation == "get_account" and (not isinstance(body.get("username"), str) or not body["username"] or type(body.get("userId")) is not int or type(body.get("teamId")) is not int):
            return {"status": "error", "error": "Reply returned an invalid account identity."}
        if config.operation.startswith("list_"):
            if not isinstance(body.get("items"), list) or type(body.get("hasMore")) is not bool:
                return {"status": "error", "error": "Reply returned an invalid paginated response."}
            if body["hasMore"] and not body["items"]:
                return {"status": "error", "error": "Reply returned an empty page with more records."}
            out.update(items=body["items"], has_more=body["hasMore"],
                next_skip=config.skip + len(body["items"]) if body["hasMore"] else None)
        else:
            out["data"] = body
        return _redact(out, secret)
