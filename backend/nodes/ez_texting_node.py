"""EZ Texting v1 operations for contacts, groups and text messaging.

Each action sends one documented request to the fixed provider API. Manual
Basic credentials avoid the provider's short-lived, password-grant tokens.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://a.eztexting.com"


class EZTextingCredential(BaseModel):
    model_config = ConfigDict(title="EZ Texting Account", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.eztexting.com/docs/authentication",
            "x-credential-instructions": "Enter your EZ Texting username and password. EZ Texting documents these same account credentials for HTTP Basic API authentication. They are sent only to a.eztexting.com over HTTPS. Connecting reads one page of your contacts; write permissions and message delivery are not verified.",
        })
    credential_type: Literal["ez_texting_basic"] = Field("ez_texting_basic", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, max_length=1024, title="Username")
    password: str = Field(..., min_length=1, max_length=4096, title="Password", json_schema_extra={"ui:widget": "password"})

    @field_validator("username", "password", mode="before")
    @classmethod
    def secrets(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use credentials without control characters")
        if info.field_name == "username" and ":" in value:
            raise ValueError("Username cannot contain a colon")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(Input):
    page: int = Field(0, ge=0, description="Zero-based page number. Each run reads one page.")
    size: Literal["10", "20", "50", "100", "200"] = Field("20", title="Page size")


class ContactBody(Input):
    phoneNumber: str = Field(..., min_length=1, max_length=100, title="Phone number")
    firstName: Optional[str] = Field(None, max_length=20, title="First name")
    lastName: Optional[str] = Field(None, max_length=20, title="Last name")
    email: Optional[str] = Field(None, json_schema_extra={"format": "email"})
    note: Optional[str] = Field(None, max_length=200)
    custom1: Optional[str] = Field(None, max_length=20)
    custom2: Optional[str] = Field(None, max_length=20)
    custom3: Optional[str] = Field(None, max_length=20)
    custom4: Optional[str] = Field(None, max_length=20)
    custom5: Optional[str] = Field(None, max_length=20)
    values: Optional[dict[str, str]] = Field(None, title="Custom field values")
    groupIdsAdd: Optional[list[str]] = Field(None, title="Group IDs to add")
    groupIdsRemove: Optional[list[str]] = Field(None, title="Group IDs to remove")

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        if value is not None and ("@" not in value or any(c.isspace() for c in value)):
            raise ValueError("Enter an email address")
        return value


class Resource(Input):
    resource_id: str = Field(..., min_length=1, max_length=512, title="Resource ID")

    @field_validator("resource_id")
    @classmethod
    def identifier(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value):
            raise ValueError("Use a resource ID")
        return value


class ContactNumber(Input):
    phoneNumber: str = Field(..., min_length=1, max_length=100, title="Phone number")

    @field_validator("phoneNumber")
    @classmethod
    def phone_segment(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value):
            raise ValueError("Use a phone number")
        return value


class GroupBody(Input):
    name: str = Field(..., min_length=1, max_length=25)
    note: Optional[str] = Field(None, max_length=500)


class TemplateBody(Input):
    name: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    companyName: Optional[str] = Field(None, title="Company name")
    mediaFileId: Optional[str] = Field(None, title="Media file ID")
    mediaFileUrl: Optional[str] = Field(None, title="Media file URL")


class ListContacts(Page):
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    phone_number: Optional[str] = Field(None, title="Phone number contains")
    first_name: Optional[str] = Field(None, title="First name contains")
    last_name: Optional[str] = Field(None, title="Last name contains")
    email: Optional[str] = Field(None, title="Email contains")
    group_name: Optional[str] = Field(None, title="Group name contains")
    opt_out: Optional[bool] = Field(None, title="Opted out")


class GetContact(ContactNumber):
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})


class UpsertContact(ContactBody):
    operation: Literal["upsert_contact"] = Field("upsert_contact", json_schema_extra={"ui:hidden": True})


class DeleteContact(ContactNumber):
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})


class ListGroups(Page):
    operation: Literal["list_groups"] = Field("list_groups", json_schema_extra={"ui:hidden": True})
    name: Optional[str] = Field(None, title="Group name contains")


class CreateGroup(GroupBody):
    operation: Literal["create_group"] = Field("create_group", json_schema_extra={"ui:hidden": True})
    phoneNumbers: Optional[list[str]] = Field(None, title="Contact phone numbers")
    groupIds: Optional[list[str]] = Field(None, title="Groups to merge")
    strictValidation: bool = Field(True, title="Require all phone numbers to be valid")


class GetGroup(Resource):
    operation: Literal["get_group"] = Field("get_group", json_schema_extra={"ui:hidden": True})


class UpdateGroup(Resource, GroupBody):
    operation: Literal["update_group"] = Field("update_group", json_schema_extra={"ui:hidden": True})


class DeleteGroup(Resource):
    operation: Literal["delete_group"] = Field("delete_group", json_schema_extra={"ui:hidden": True})


class AddGroupContacts(Resource):
    operation: Literal["add_group_contacts"] = Field("add_group_contacts", json_schema_extra={"ui:hidden": True})
    phoneNumbers: list[str] = Field(..., min_length=1, title="Contact phone numbers")


class RemoveGroupContacts(Resource):
    operation: Literal["remove_group_contacts"] = Field("remove_group_contacts", json_schema_extra={"ui:hidden": True})
    phoneNumbers: list[str] = Field(..., min_length=1, title="Contact phone numbers")


class ListMessages(Page):
    operation: Literal["list_messages"] = Field("list_messages", json_schema_extra={"ui:hidden": True})
    user_number: Optional[str] = Field(None, title="Sending phone number")
    contact_number: Optional[str] = Field(None, title="Contact phone number")
    incoming: Optional[bool] = None
    unread: Optional[bool] = None
    text_query: Optional[str] = Field(None, title="Message text query")


class SendMessage(Input):
    operation: Literal["send_message"] = Field("send_message", json_schema_extra={"ui:hidden": True})
    message: Optional[str] = Field(None, min_length=1, title="Message text")
    messageTemplateId: Optional[str] = Field(None, min_length=1, title="Message template ID")
    toNumbers: Optional[list[str]] = Field(None, min_length=1, title="Recipient phone numbers")
    groupIds: Optional[list[str]] = Field(None, min_length=1, title="Recipient group IDs")
    fromNumber: Optional[str] = Field(None, title="Sending number", description="Required by EZ Texting when the account has multiple sending numbers.")
    companyName: Optional[str] = Field(None, title="Company name")
    sendAt: Optional[str] = Field(None, title="Send at", json_schema_extra={"format": "date-time"}, description="ISO 8601 date and time with timezone; omit to send immediately.")
    mediaFileId: Optional[str] = Field(None, title="Media file ID")
    mediaUrl: Optional[str] = Field(None, title="Media URL")
    messageType: Literal["SMS", "MMS"] = Field("SMS", title="Message type")
    strictValidation: bool = Field(True, title="Require all recipients to be valid")

    @model_validator(mode="after")
    def recipients_and_text(self):
        if not (self.toNumbers or self.groupIds):
            raise ValueError("Provide recipient phone numbers or group IDs")
        if not (self.message or self.messageTemplateId):
            raise ValueError("Provide message text or a message template ID")
        if self.sendAt:
            try:
                parsed = datetime.fromisoformat(self.sendAt.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise ValueError("Send at must be an ISO 8601 date and time with timezone") from None
        return self


class DeleteMessages(Input):
    operation: Literal["delete_messages"] = Field("delete_messages", json_schema_extra={"ui:hidden": True})
    ids: list[int] = Field(..., min_length=1, title="Message IDs")


class GetMessageDetails(Resource):
    operation: Literal["get_message_details"] = Field("get_message_details", json_schema_extra={"ui:hidden": True})


class GetMessageReport(Resource):
    operation: Literal["get_message_report"] = Field("get_message_report", json_schema_extra={"ui:hidden": True})


class ListTemplates(Page):
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})
    name: Optional[str] = Field(None, title="Template name contains")


class CreateTemplate(TemplateBody):
    operation: Literal["create_template"] = Field("create_template", json_schema_extra={"ui:hidden": True})


class GetTemplate(Resource):
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})


class UpdateTemplate(Resource, TemplateBody):
    operation: Literal["update_template"] = Field("update_template", json_schema_extra={"ui:hidden": True})


class DeleteTemplate(Resource):
    operation: Literal["delete_template"] = Field("delete_template", json_schema_extra={"ui:hidden": True})


class GetCreditBalance(Input):
    operation: Literal["get_credit_balance"] = Field("get_credit_balance", json_schema_extra={"ui:hidden": True})


class ListContactFields(Page):
    operation: Literal["list_contact_fields"] = Field("list_contact_fields", json_schema_extra={"ui:hidden": True})


class BlockNumbers(Input):
    operation: Literal["block_numbers"] = Field("block_numbers", json_schema_extra={"ui:hidden": True})
    phoneNumbers: list[str] = Field(..., min_length=1, title="Phone numbers to block")


EZTextingOperation = Annotated[Union[
    ListContacts,
    GetContact,
    UpsertContact,
    DeleteContact,
    ListGroups,
    CreateGroup,
    GetGroup,
    UpdateGroup,
    DeleteGroup,
    AddGroupContacts,
    RemoveGroupContacts,
    ListMessages,
    SendMessage,
    DeleteMessages,
    GetMessageDetails,
    GetMessageReport,
    ListTemplates,
    CreateTemplate,
    GetTemplate,
    UpdateTemplate,
    DeleteTemplate,
    GetCreditBalance,
    ListContactFields,
    BlockNumbers
], Field(discriminator="operation")]


class EZTextingConfig(NodeConfig[EZTextingOperation, EZTextingCredential]):
    pass


ROUTES = {
    "list_contacts": ("GET", "/v1/contacts"),
    "get_contact": ("GET", "/v1/contacts/{phoneNumber}"),
    "upsert_contact": ("POST", "/v1/contacts"),
    "delete_contact": ("DELETE", "/v1/contacts/{phoneNumber}"),
    "list_groups": ("GET", "/v1/contact-groups"),
    "create_group": ("POST", "/v1/contact-groups"),
    "get_group": ("GET", "/v1/contact-groups/{id}"),
    "update_group": ("PUT", "/v1/contact-groups/{id}"),
    "delete_group": ("DELETE", "/v1/contact-groups/{id}"),
    "add_group_contacts": ("POST", "/v1/contact-groups/{id}/contacts"),
    "remove_group_contacts": ("DELETE", "/v1/contact-groups/{id}/contacts"),
    "list_messages": ("GET", "/v1/messages"),
    "send_message": ("POST", "/v1/messages"),
    "delete_messages": ("DELETE", "/v1/messages"),
    "get_message_details": ("GET", "/v1/message-details/{id}"),
    "get_message_report": ("GET", "/v1/message-reports/{id}"),
    "list_templates": ("GET", "/v1/message-templates"),
    "create_template": ("POST", "/v1/message-templates"),
    "get_template": ("GET", "/v1/message-templates/{id}"),
    "update_template": ("PUT", "/v1/message-templates/{id}"),
    "delete_template": ("DELETE", "/v1/message-templates/{id}"),
    "get_credit_balance": ("GET", "/v1/credits"),
    "list_contact_fields": ("GET", "/v1/contact-fields"),
    "block_numbers": ("POST", "/v1/blocks"),
}

FILTERS = {
    "list_contacts": {"phone_number": "filters[phoneNumber][like]", "first_name": "filters[firstName][like]",
        "last_name": "filters[lastName][like]", "email": "filters[email][like]",
        "group_name": "filters[groupName][like]", "opt_out": "filters[optOut][eq]"},
    "list_groups": {"name": "filters[name][like]"},
    "list_templates": {"name": "filters[name][like]"},
    "list_messages": {"user_number": "filters[userNumber][eq]", "contact_number": "filters[contactNumber][eq]",
        "incoming": "filters[incoming][eq]", "unread": "filters[unread][eq]", "text_query": "filters[textQuery][eq]"},
}


def _redact(value, credential):
    # Provider errors can echo request headers. Redact both raw and encoded auth.
    secrets = (credential.password, credential.username,
        httpx.BasicAuth(credential.username, credential.password)._auth_header)
    if isinstance(value, str):
        for secret in sorted(secrets, key=len, reverse=True):
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(v, credential) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, credential) for k, v in value.items()}
    return value


class EZTextingNode(WorkflowNode):
    integration_type = "automation-ez-texting"
    connection_evidence = ConnectionEvidence(noun="contacts", operation="list_contacts",
        label_keys=("firstName", "lastName", "phoneNumber", "email"))

    @classmethod
    def get_config_model(cls):
        return EZTextingConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an EZ Texting account")
        credential, op = self.config.credentials, self.config.config
        method, route = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        if "{id}" in route:
            route = route.replace("{id}", quote(values.pop("resource_id"), safe=""))
        if "{phoneNumber}" in route:
            route = route.replace("{phoneNumber}", quote(values.pop("phoneNumber"), safe=""))
        params, body = {}, None
        if isinstance(op, Page):
            params = {"page": values.pop("page"), "size": values.pop("size")}
            for key, wire in FILTERS.get(op.operation, {}).items():
                if key in values:
                    value = values.pop(key)
                    params[wire] = str(value).lower() if isinstance(value, bool) else value
        elif isinstance(op, (AddGroupContacts, RemoveGroupContacts)):
            params["phoneNumbers"] = values.pop("phoneNumbers")
        elif values:
            body = values
        writing = method != "GET"
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + route,
                    auth=httpx.BasicAuth(credential.username, credential.password),
                    headers={"Accept": "application/json"}, params=params,
                    **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            return {"status": "unknown" if writing else "error", "success": False,
                "error": "EZ Texting request did not complete; inspect writes before retrying"}
        if not 200 <= response.status_code < 300:
            return _redact({"status": "error", "success": False, "http_status": response.status_code,
                "error": response.text[:4000]}, credential)
        try:
            data = response.json() if response.content else None
        except ValueError:
            raise ValueError("EZ Texting returned an unexpected non-JSON response") from None
        if isinstance(data, dict) and (data.get("errors") or data.get("error")):
            return _redact({"status": "error", "success": False, "error": data}, credential)
        result = {"status": "success", "success": True, "operation": op.operation,
            "http_status": response.status_code}
        if isinstance(op, Page):
            if not isinstance(data, dict) or not isinstance(data.get("content"), list):
                raise ValueError("EZ Texting returned an invalid page envelope")
            result.update(data=data["content"], pagination={key: data.get(key) for key in
                ("number", "size", "totalElements", "totalPages", "numberOfElements")})
            number, total_pages = data.get("number"), data.get("totalPages")
            result["next_page"] = number + 1 if type(number) is int and type(total_pages) is int and number + 1 < total_pages else None
        else:
            result["data"] = data
        if writing:
            result["acknowledged"] = True
            if isinstance(op, SendMessage):
                result["delivery_verified"] = False
        return _redact(result, credential)
