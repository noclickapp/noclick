"""Tidio OpenAPI v1 contacts, conversations and support tickets.

Contract: https://developers.tidio.com/reference/get_project
Authentication: https://developers.tidio.com/docs/openapi-authorization
Each operation makes one request; cursor pagination remains caller controlled.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.tidio.com"
MEDIA_TYPE = "application/json; version=1"


class TidioAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Tidio API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "api_key",
        "x-credential-url": "https://www.tidio.com/panel/",
        "x-credential-instructions": "In Tidio, open Developer > OpenAPI and generate an API key as a project owner or admin. Paste both the client ID (ci_…) and client secret (cs_…). Enable OpenAPI and the permissions needed by your operations. NoClick verifies the authenticated project.",
        "x-help-url": "https://developers.tidio.com/docs/openapi-authorization",
    })
    credential_type: Literal["tidio_api_key"] = Field("tidio_api_key", json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., title="Client ID", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    client_secret: str = Field(..., title="Client Secret", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("client_id", "client_secret", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="Tidio API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the key without spaces or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class _Page(_Input):
    cursor: str | None = Field(None, title="Cursor", max_length=8192, description="Copy meta.cursor from the previous response; omit for the first page. One page per execution.")


class _Contact(_Input):
    contact_id: UUID = Field(..., title="Contact ID")


class _Ticket(_Input):
    ticket_id: int = Field(..., title="Ticket ID", ge=1)


class _ContactFields(_Input):
    distinct_id: str | None = Field(None, max_length=55, title="External Contact ID")
    email: str | None = Field(None, title="Email", json_schema_extra={"format": "email"})
    phone: str | None = Field(None, max_length=155)
    first_name: str | None = Field(None, max_length=127)
    last_name: str | None = Field(None, max_length=127)
    email_consent: Literal["subscribed", "unsubscribed"] | None = None


class ContactProperty(_Input):
    name: str = Field(..., min_length=1, max_length=128)
    value: str = Field(..., max_length=1000)


class ContactPropertyUpdate(_Input):
    name: str = Field(..., min_length=1, max_length=128)
    value: str | None = Field(..., max_length=1000, description="Null clears the stored property value.")


class CustomFieldCreate(_Input):
    id: str = Field(..., min_length=1)
    value: str = Field(..., max_length=65535)


class CustomFieldUpdate(_Input):
    id: str = Field(..., min_length=1)
    value: str | None = Field(..., max_length=65535, description="Null removes the field value.")


class TicketAssignment(_Input):
    type: Literal["department", "operator"]
    id: UUID


class GetProject(_Input):
    operation: Literal["get_project"] = Field("get_project", title="Get Project", json_schema_extra={"ui:hidden": True})


class ListContacts(_Page):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})
    email: str | None = Field(None, title="Email Filter", json_schema_extra={"format": "email"})


class CreateContact(_ContactFields):
    operation: Literal["create_contact"] = Field("create_contact", title="Create Contact", json_schema_extra={"ui:hidden": True})
    distinct_id: str = Field(..., min_length=1, max_length=55, title="External Contact ID")
    properties: list[ContactProperty] | None = None

    @model_validator(mode="after")
    def identified(self):
        if not any((self.email, self.phone, self.first_name, self.last_name)):
            raise ValueError("Provide at least one of email, phone, first name or last name")
        return self


class GetContact(_Contact):
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})


class UpdateContact(_Contact, _ContactFields):
    operation: Literal["update_contact"] = Field("update_contact", title="Update Contact", json_schema_extra={"ui:hidden": True})
    properties: list[ContactPropertyUpdate] | None = None


class DeleteContact(_Contact):
    operation: Literal["delete_contact"] = Field("delete_contact", title="Delete Contact", description="Permanently deletes this contact.", json_schema_extra={"ui:hidden": True})


class ListViewedPages(_Contact, _Page):
    operation: Literal["list_viewed_pages"] = Field("list_viewed_pages", title="List Viewed Pages", json_schema_extra={"ui:hidden": True})


class SendContactMessage(_Contact):
    operation: Literal["send_contact_message"] = Field("send_contact_message", title="Send Message as Contact", description="Submits a message on behalf of the contact. Acceptance is asynchronous and does not prove delivery.", json_schema_extra={"ui:hidden": True})
    message: str = Field(..., min_length=1, max_length=5000)


class ListContactMessages(_Contact, _Page):
    operation: Literal["list_contact_messages"] = Field("list_contact_messages", title="List Contact Messages", json_schema_extra={"ui:hidden": True})


class ListContactProperties(_Page):
    operation: Literal["list_contact_properties"] = Field("list_contact_properties", title="List Contact Properties", json_schema_extra={"ui:hidden": True})


class ListOperators(_Page):
    operation: Literal["list_operators"] = Field("list_operators", title="List Operators", json_schema_extra={"ui:hidden": True})


class CreateTicket(_Input):
    operation: Literal["create_ticket"] = Field("create_ticket", title="Create Ticket as Contact", description="Creates a support ticket with the contact's first message; Tidio may send notifications.", json_schema_extra={"ui:hidden": True})
    contact_email: str = Field(..., json_schema_extra={"format": "email"})
    subject: str = Field(..., min_length=1)
    message_content: str = Field(..., min_length=1)
    assigned_department_id: UUID | None = None
    custom_channel_id: str | None = None
    tag_ids: list[Annotated[int, Field(ge=1)]] | None = None
    custom_fields: list[CustomFieldCreate] | None = None


class ListTickets(_Page):
    operation: Literal["list_tickets"] = Field("list_tickets", title="List Tickets", json_schema_extra={"ui:hidden": True})


class ListTicketTags(_Input):
    operation: Literal["list_ticket_tags"] = Field("list_ticket_tags", title="List Ticket Tags", json_schema_extra={"ui:hidden": True})


class ListTicketCustomFields(_Input):
    operation: Literal["list_ticket_custom_fields"] = Field("list_ticket_custom_fields", title="List Ticket Custom Fields", json_schema_extra={"ui:hidden": True})


class GetTicket(_Ticket):
    operation: Literal["get_ticket"] = Field("get_ticket", title="Get Ticket", json_schema_extra={"ui:hidden": True})


class UpdateTicket(_Ticket):
    operation: Literal["update_ticket"] = Field("update_ticket", title="Update Ticket", json_schema_extra={"ui:hidden": True})
    status: Literal["open", "pending", "solved"] | None = None
    priority: Literal["low", "normal", "urgent"] | None = None
    assigned: TicketAssignment | None = Field(None, description="Null unassigns the ticket; omit to keep the current assignment.")
    tag_ids: list[Annotated[int, Field(ge=1)]] | None = Field(None, description="Replaces the full tag set. An empty list removes all tags.")
    custom_fields: list[CustomFieldUpdate] | None = Field(None, max_length=100, description="Merges specified values; null values remove stored fields.")


class DeleteTicket(_Ticket):
    operation: Literal["delete_ticket"] = Field("delete_ticket", title="Delete Ticket", description="Deletes the ticket.", json_schema_extra={"ui:hidden": True})


class ReplyTicket(_Ticket):
    operation: Literal["reply_ticket"] = Field("reply_ticket", title="Reply to Ticket", description="Sends a public reply or internal note with the specified author.", json_schema_extra={"ui:hidden": True})
    author_type: Literal["contact", "operator"] = Field(...)
    content: str = Field(..., min_length=1)
    operator_id: UUID | None = None
    message_type: Literal["public", "internal"] | None = None

    @model_validator(mode="after")
    def operator_required(self):
        if self.author_type == "operator" and not self.operator_id:
            raise ValueError("Provide an operator ID when replying as an operator")
        return self


class ListDepartments(_Input):
    operation: Literal["list_departments"] = Field("list_departments", title="List Departments", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[GetProject, ListContacts, CreateContact, GetContact, UpdateContact, DeleteContact,
    ListViewedPages, SendContactMessage, ListContactMessages, ListContactProperties, ListOperators,
    CreateTicket, ListTickets, ListTicketTags, ListTicketCustomFields, GetTicket, UpdateTicket,
    DeleteTicket, ReplyTicket, ListDepartments], Field(discriminator="operation")]


class TidioConfig(NodeConfig[Operation, TidioAPIKeyCredential]):
    pass


# operation -> method, contract route, expected success code
ROUTES = {
    "get_project": ("GET", "/project", 200),
    "list_contacts": ("GET", "/contacts", 200),
    "create_contact": ("POST", "/contacts", 201),
    "get_contact": ("GET", "/contacts/{contact_id}", 200),
    "update_contact": ("PATCH", "/contacts/{contact_id}", 204),
    "delete_contact": ("DELETE", "/contacts/{contact_id}", 204),
    "list_viewed_pages": ("GET", "/contacts/{contact_id}/viewed-pages", 200),
    "send_contact_message": ("POST", "/contacts/{contact_id}/messages", 202),
    "list_contact_messages": ("GET", "/contacts/{contact_id}/messages", 200),
    "list_contact_properties": ("GET", "/contact-properties", 200),
    "list_operators": ("GET", "/operators", 200),
    "create_ticket": ("POST", "/tickets/as-contact", 201),
    "list_tickets": ("GET", "/tickets", 200),
    "list_ticket_tags": ("GET", "/tickets/tags", 200),
    "list_ticket_custom_fields": ("GET", "/tickets/custom-fields", 200),
    "get_ticket": ("GET", "/tickets/{ticket_id}", 200),
    "update_ticket": ("PATCH", "/tickets/{ticket_id}", 204),
    "delete_ticket": ("DELETE", "/tickets/{ticket_id}", 204),
    "reply_ticket": ("POST", "/tickets/{ticket_id}/reply", 201),
    "list_departments": ("GET", "/departments", 200),
}


class TidioNode(WorkflowNode):
    integration_type = "automation-tidio"
    connection_evidence = ConnectionEvidence(noun="Tidio project", identity_operation="get_project", identity_keys=("project_id",))

    @classmethod
    def get_config_model(cls):
        return TidioConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Tidio API key")
        config = self.config.config
        credential = self.config.credentials
        method, route, expected = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_unset=True, exclude={"operation"})
        for field in ("contact_id", "ticket_id"):
            if field in values:
                route = route.replace("{" + field + "}", str(values.pop(field)))
        if method == "GET":
            values = {k: v for k, v in values.items() if v is not None}
        elif method in {"POST", "PATCH"}:
            # Only these nullable fields have documented clearing semantics.
            nullable = {"email", "phone", "first_name", "last_name", "email_consent", "assigned"}
            values = {k: v for k, v in values.items() if v is not None or k in nullable}
            if method == "PATCH" and not values:
                raise ValueError("Provide at least one property to update")
        headers = {"Accept": MEDIA_TYPE,
            "X-Tidio-Openapi-Client-Id": credential.client_id,
            "X-Tidio-Openapi-Client-Secret": credential.client_secret}
        kwargs = {"params": values} if method == "GET" else {}
        if method in {"POST", "PATCH"}:
            headers["Content-Type"] = MEDIA_TYPE
            kwargs["json"] = values
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + route, headers=headers, **kwargs)
        if response.status_code != expected:
            message = f"Tidio returned HTTP {response.status_code}"
            try:
                errors = response.json().get("errors", [])
                detail = "; ".join(e["message"] for e in errors if isinstance(e, dict) and isinstance(e.get("message"), str))
                if detail:
                    message += ": " + detail[:2000]
            except (ValueError, AttributeError, TypeError):
                pass
            for secret in (credential.client_id, credential.client_secret):
                message = message.replace(secret, "[redacted]")
            raise ValueError(message)
        if expected == 204:
            return {"status": "success", "status_code": expected, "data": None}
        payload = response.json()
        if not isinstance(payload, (dict, list)) or isinstance(payload, dict) and payload.get("errors"):
            raise ValueError("Tidio returned an unexpected response")
        return {"status": "success", "status_code": expected, "data": payload}
