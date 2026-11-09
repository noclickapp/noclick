"""Textmagic v2 messaging, contacts and reusable content via a pasted API key.

Each operation makes one documented request; paginated reads expose continuation
without silently walking the account. Sending acknowledges acceptance, not delivery.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://rest.textmagic.com/api/v2"


class TextmagicAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Textmagic API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.textmagic.com/settings/api",
            "x-credential-instructions": "Open Textmagic Settings → API and paste your API username and API key. Use the API key, not your account password. NoClick checks the current account with a read-only request.",
        })
    credential_type: Literal["textmagic_api_key"] = Field("textmagic_api_key", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, max_length=255, title="API username", description="Copy the username shown with your Textmagic API key.")
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("username")
    @classmethod
    def valid_username(cls, value):
        value = value.strip()
        if not value or ":" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API username without a colon or control characters")
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def valid_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    page: int = Field(1, ge=1, description="Results page to fetch. Use next_page from the preceding response.")
    limit: int = Field(10, ge=1, le=100, description="Results per page. Only one page is fetched.")


class _ID(_Input):
    id: int = Field(..., ge=1, title="Resource ID")


class _Contact(_Input):
    phone: str = Field(..., pattern=r"^[1-9][0-9]{5,14}$", description="International E.164 phone digits, for example 447860021130.")
    lists: str = Field(..., pattern=r"^[1-9][0-9]*(,[1-9][0-9]*)*$", description="Comma-separated list IDs. A contact must belong to at least one list.")
    first_name: str | None = Field(None, title="First name")
    last_name: str | None = Field(None, title="Last name")
    email: str | None = Field(None, json_schema_extra={"format": "email"})
    company_name: str | None = Field(None, title="Company name")
    favorited: bool | None = None


class _Template(_Input):
    name: str = Field(..., min_length=1, title="Template name")
    content: str = Field(..., min_length=1, title="Template text", json_schema_extra={"ui:widget": "textarea"})


class GetAccount(_Input):
    """Get current account information."""
    operation: Literal["get_account"] = Field("get_account", title="Get Account", json_schema_extra={"ui:hidden": True})


class SendMessage(_Input):
    """Send message."""
    operation: Literal["send_message"] = Field("send_message", title="Send Message", json_schema_extra={"ui:hidden": True})
    text: str = Field(..., min_length=1, title="Message text", json_schema_extra={"ui:widget": "textarea"})
    phones: str = Field(..., pattern=r"^[1-9][0-9]{5,14}(,[1-9][0-9]{5,14})*$", description="Comma-separated E.164 phone digits. Sending uses paid Textmagic credit.")
    sender: str | None = Field(None, title="Sender ID", description="An approved sender ID or phone number. Textmagic may fall back to the default sender.")
    sending_date_time: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:[1-5]\d$", description="Optional scheduled local time YYYY-MM-DD HH:MM:SS; seconds must be at least 10.")
    sending_timezone: str | None = Field(None, description="Timezone name for scheduled sending, for example America/Buenos_Aires. Defaults to the account timezone.")
    reference_id: int | None = Field(None, title="Reference ID")
    parts_count: int = Field(6, ge=1, le=6, title="Maximum message parts")
    cut_extra: bool = Field(False, description="Cut text exceeding the maximum parts instead of returning an error.")


class ListMessages(_Page):
    """Get all messages."""
    operation: Literal["list_messages"] = Field("list_messages", title="List Messages", json_schema_extra={"ui:hidden": True})


class GetMessage(_ID):
    """Get a single message."""
    operation: Literal["get_message"] = Field("get_message", title="Get Message", json_schema_extra={"ui:hidden": True})


class DeleteMessage(_ID):
    """Delete message."""
    operation: Literal["delete_message"] = Field("delete_message", title="Delete Message", json_schema_extra={"ui:hidden": True})


class ListReplies(_Page):
    """Get all inbound messages."""
    operation: Literal["list_replies"] = Field("list_replies", title="List Replies", json_schema_extra={"ui:hidden": True})


class GetReply(_ID):
    """Get a single inbound message."""
    operation: Literal["get_reply"] = Field("get_reply", title="Get Reply", json_schema_extra={"ui:hidden": True})


class ListSchedules(_Page):
    """Get all scheduled messages."""
    operation: Literal["list_schedules"] = Field("list_schedules", title="List Schedules", json_schema_extra={"ui:hidden": True})


class GetSchedule(_ID):
    """Get a single scheduled message."""
    operation: Literal["get_schedule"] = Field("get_schedule", title="Get Schedule", json_schema_extra={"ui:hidden": True})


class DeleteSchedule(_ID):
    """Delete a single scheduled message."""
    operation: Literal["delete_schedule"] = Field("delete_schedule", title="Delete Schedule", json_schema_extra={"ui:hidden": True})


class ListContacts(_Page):
    """Get all contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})


class GetContact(_ID):
    """Get the details of a specific contact."""
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})


class CreateContact(_Contact):
    """Add a new contact."""
    operation: Literal["create_contact"] = Field("create_contact", title="Create Contact", json_schema_extra={"ui:hidden": True})


class UpdateContact(_Contact, _ID):
    """Edit a contact."""
    operation: Literal["update_contact"] = Field("update_contact", title="Update Contact", json_schema_extra={"ui:hidden": True})


class DeleteContact(_ID):
    """Delete a contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", title="Delete Contact", json_schema_extra={"ui:hidden": True})


class ListContactLists(_Page):
    """Get all lists."""
    operation: Literal["list_contact_lists"] = Field("list_contact_lists", title="List Contact Lists", json_schema_extra={"ui:hidden": True})


class GetContactList(_ID):
    """Get the details of a specific list."""
    operation: Literal["get_contact_list"] = Field("get_contact_list", title="Get Contact List", json_schema_extra={"ui:hidden": True})


class CreateContactList(_Input):
    """Create a new list."""
    operation: Literal["create_contact_list"] = Field("create_contact_list", title="Create Contact List", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, title="List name")
    shared: bool = Field(False, description="Share the list with all subaccounts.")


class AddContactsToList(_ID):
    """Assign contacts to a list."""
    operation: Literal["add_contacts_to_list"] = Field("add_contacts_to_list", title="Add Contacts To List", json_schema_extra={"ui:hidden": True})
    contacts: str = Field(..., pattern=r"^[1-9][0-9]*(,[1-9][0-9]*)*$", description="Comma-separated contact IDs to add without replacing existing members.")


class ListContactsInList(_Page, _ID):
    """Get all contacts in a list."""
    operation: Literal["list_contacts_in_list"] = Field("list_contacts_in_list", title="List Contacts In List", json_schema_extra={"ui:hidden": True})


class ListTemplates(_Page):
    """Get all templates."""
    operation: Literal["list_templates"] = Field("list_templates", title="List Templates", json_schema_extra={"ui:hidden": True})


class GetTemplate(_ID):
    """Get a template`s details."""
    operation: Literal["get_template"] = Field("get_template", title="Get Template", json_schema_extra={"ui:hidden": True})


class CreateTemplate(_Template):
    """Create a template."""
    operation: Literal["create_template"] = Field("create_template", title="Create Template", json_schema_extra={"ui:hidden": True})


class UpdateTemplate(_Template, _ID):
    """Update a template."""
    operation: Literal["update_template"] = Field("update_template", title="Update Template", json_schema_extra={"ui:hidden": True})


class DeleteTemplate(_ID):
    """Delete a template."""
    operation: Literal["delete_template"] = Field("delete_template", title="Delete Template", json_schema_extra={"ui:hidden": True})


TextmagicOperation = Annotated[Union[
    GetAccount,
    SendMessage,
    ListMessages,
    GetMessage,
    DeleteMessage,
    ListReplies,
    GetReply,
    ListSchedules,
    GetSchedule,
    DeleteSchedule,
    ListContacts,
    GetContact,
    CreateContact,
    UpdateContact,
    DeleteContact,
    ListContactLists,
    GetContactList,
    CreateContactList,
    AddContactsToList,
    ListContactsInList,
    ListTemplates,
    GetTemplate,
    CreateTemplate,
    UpdateTemplate,
    DeleteTemplate
], Field(discriminator="operation")]


class TextmagicFullConfig(NodeConfig[TextmagicOperation, TextmagicAPIKeyCredential]):
    pass


OPERATIONS = {
    "get_account": ("GET", "/user"),
    "send_message": ("POST", "/messages"),
    "list_messages": ("GET", "/messages"),
    "get_message": ("GET", "/messages/{id}"),
    "delete_message": ("DELETE", "/messages/{id}"),
    "list_replies": ("GET", "/replies"),
    "get_reply": ("GET", "/replies/{id}"),
    "list_schedules": ("GET", "/schedules"),
    "get_schedule": ("GET", "/schedules/{id}"),
    "delete_schedule": ("DELETE", "/schedules/{id}"),
    "list_contacts": ("GET", "/contacts"),
    "get_contact": ("GET", "/contacts/{id}"),
    "create_contact": ("POST", "/contacts/normalized"),
    "update_contact": ("PUT", "/contacts/{id}/normalized"),
    "delete_contact": ("DELETE", "/contacts/{id}"),
    "list_contact_lists": ("GET", "/lists"),
    "get_contact_list": ("GET", "/lists/{id}"),
    "create_contact_list": ("POST", "/lists"),
    "add_contacts_to_list": ("PUT", "/lists/{id}/contacts"),
    "list_contacts_in_list": ("GET", "/lists/{id}/contacts"),
    "list_templates": ("GET", "/templates"),
    "get_template": ("GET", "/templates/{id}"),
    "create_template": ("POST", "/templates"),
    "update_template": ("PUT", "/templates/{id}"),
    "delete_template": ("DELETE", "/templates/{id}"),
}

WIRE_NAMES = {
    "first_name": "firstName", "last_name": "lastName", "company_name": "companyName",
    "sender": "from", "sending_date_time": "sendingDateTime", "sending_timezone": "sendingTimezone",
    "reference_id": "referenceId", "parts_count": "partsCount", "cut_extra": "cutExtra",
}


class TextmagicNode(WorkflowNode):
    integration_type = "automation-textmagic"
    connection_evidence = ConnectionEvidence(noun="Textmagic account", identity_operation="get_account", identity_keys=("username", "email"))

    @classmethod
    def get_config_model(cls):
        return TextmagicFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Textmagic API key")
        op = self.config.config
        credential = self.config.credentials
        method, path = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            path = path.replace("{id}", str(values.pop("id")))
        values = {WIRE_NAMES.get(k, k): v for k, v in values.items()}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    auth=httpx.BasicAuth(credential.username, credential.api_key),
                    headers={"Accept": "application/json"},
                    **({"params": values} if method == "GET" else {"json": values} if values else {}))
        except httpx.RequestError:
            return {"status": "error", "error": "Textmagic request could not be completed"}

        if not 200 <= response.status_code < 300:
            message = "Textmagic request rejected"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"].replace(credential.api_key, "[redacted]")
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": message}
        expected = {200} if method == "GET" else {204} if method == "DELETE" else {201, 202} if op.operation == "send_message" else {201}
        if response.status_code not in expected:
            return {"status": "error", "http_status": response.status_code, "error": "Unexpected Textmagic response status"}
        if response.status_code == 204:
            return {"status": "success", "http_status": 204, "deletion_acknowledged": True}
        if response.status_code == 202 and op.operation == "send_message":
            return {"status": "success", "http_status": 202, "accepted": True, "delivery_verified": False}
        try:
            body = response.json()
        except ValueError:
            return {"status": "error", "error": "Expected Textmagic JSON response"}
        if not isinstance(body, dict) or "error" in body or "errors" in body:
            return {"status": "error", "error": "Unexpected Textmagic response"}
        if not isinstance(op, _Page) and type(body.get("id")) is not int:
            return {"status": "error", "error": "Expected a Textmagic resource ID"}
        if op.operation == "get_account" and not isinstance(body.get("username"), str):
            return {"status": "error", "error": "Expected a Textmagic account username"}
        # The provider's resource and pagination fields remain available to downstream nodes.
        result = {"status": "success", "http_status": response.status_code, "data": body}
        if isinstance(op, _Page):
            if not isinstance(body.get("resources"), list) or any(type(body.get(k)) is not int for k in ("page", "pageCount", "limit")):
                return {"status": "error", "error": "Unexpected Textmagic paginated response"}
            result.update(items=body["resources"], next_page=body["page"] + 1 if body["page"] < body["pageCount"] else None)
        if op.operation == "send_message":
            result.update(accepted=True, delivery_verified=False)
        return result
