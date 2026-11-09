"""Sakari SMS v1, pinned to the provider's published OpenAPI 1.0.2.

API clients use the documented client_credentials grant, not interactive OAuth.
Tokens live for one execution only. Each operation makes one resource request;
list operations return one page and sending acknowledges acceptance, not delivery.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

API = "https://api.sakari.io"
HIDDEN = {"ui:hidden": True}


def _id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
        raise ValueError("Paste one Sakari ID, without a URL or path")
    return value


class SakariSMSAPICredential(BaseModel):
    model_config = ConfigDict(title="Sakari SMS API Client", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.sakari.io/quickstart",
            "x-credential-instructions": "In Sakari, open Account Details (the cog) and find API Credentials. Paste the account ID, client ID and client secret. NoClick exchanges the client credentials for a temporary token at api.sakari.io for each operation. Listing contacts checks this account's read access; Sakari controls write permissions."
        })
    credential_type: Literal["sakari_sms_api_credentials"] = Field("sakari_sms_api_credentials", json_schema_extra=HIDDEN)
    account_id: str = Field(..., title="Account ID", min_length=1, max_length=200)
    client_id: str = Field(..., title="Client ID", min_length=1, max_length=4096, repr=False)
    client_secret: str = Field(..., title="Client Secret", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("account_id")
    @classmethod
    def account(cls, value):
        return _id(value.strip())

    @field_validator("client_id", "client_secret")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the credential without whitespace")
        return value


def _operation(name, category, description):
    return Field(name, description=description, json_schema_extra={**HIDDEN,
        "x-display-name": name.replace("_", " ").title(), "x-category": category, "x-is-trigger": False})


class Input(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @field_validator("contact_id", "template_id", "message_id", "conversation_id", check_fields=False)
    @classmethod
    def identifier(cls, value):
        return _id(value) if value is not None else None


class Page(Input):
    offset: int = Field(0, ge=0, description="Results to skip. Lists return exactly one page.")
    limit: int = Field(25, ge=1, le=100)


class GetAccount(Input):
    operation: Literal["get_account"] = _operation("get_account", "Account", "Read account details, excluding API credentials and billing details.")


class ListContacts(Page):
    operation: Literal["list_contacts"] = _operation("list_contacts", "Contacts", "List or search contacts in one account.")
    first_name: str | None = None
    last_name: str | None = None
    mobile: str | None = None
    email: str | None = None
    tags: str | None = Field(None, description="Provider tag filter string.")


class GetContact(Input):
    operation: Literal["get_contact"] = _operation("get_contact", "Contacts", "Read a contact by ID.")
    contact_id: str


class ContactFields(Input):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    mobile_number: str = Field(..., description="International phone number, including + and country calling code.")
    country: str | None = Field(None, pattern=r"^[A-Z]{2}$", description="Two-letter country code, for example US.")
    attributes: dict[str, Any] | None = Field(None, description="Custom contact attributes.")

    @field_validator("mobile_number")
    @classmethod
    def mobile(cls, value):
        if not re.fullmatch(r"\+[1-9][0-9]{6,14}", value):
            raise ValueError("Use an international phone number such as +1234567890")
        return value


class CreateContact(ContactFields):
    operation: Literal["create_contact"] = _operation("create_contact", "Contacts", "Create a contact, or merge an existing contact with the same mobile number.")
    merge_strategy: Literal["append", "core", "remove"] | None = None


class UpdateContact(ContactFields):
    operation: Literal["update_contact"] = _operation("update_contact", "Contacts", "Update a contact's mobile number and supplied profile fields.")
    contact_id: str


class DeleteContact(Input):
    operation: Literal["delete_contact"] = _operation("delete_contact", "Contacts", "Delete a contact permanently.")
    contact_id: str


class ListMessages(Page):
    operation: Literal["list_messages"] = _operation("list_messages", "Messages", "Read message history, optionally for one contact or conversation.")
    contact_id: str | None = None
    conversation_id: str | None = None


class GetMessage(Input):
    operation: Literal["get_message"] = _operation("get_message", "Messages", "Read a message and its provider delivery status.")
    message_id: str


class SendMessage(Input):
    operation: Literal["send_message"] = _operation("send_message", "Messages", "Send an SMS to an explicit international phone number. Acceptance does not prove delivery; do not automatically retry an uncertain send.")
    mobile_number: str
    country: str | None = Field(None, pattern=r"^[A-Z]{2}$")
    template: str = Field(..., min_length=1, description="SMS text, optionally with Sakari contact placeholders.")
    group_id: str | None = Field(None, description="Optional sending phone-number group ID.")
    _phone = field_validator("mobile_number")(ContactFields.mobile.__func__)
    _group = field_validator("group_id")(lambda v: _id(v) if v is not None else v)


class ListTemplates(Page):
    operation: Literal["list_templates"] = _operation("list_templates", "Templates", "List templates with an optional name filter.")
    name: str | None = None


class GetTemplate(Input):
    operation: Literal["get_template"] = _operation("get_template", "Templates", "Read one reusable template.")
    template_id: str


class TemplateFields(Input):
    name: str = Field(..., min_length=1)
    template: str = Field(..., min_length=1)
    template_type: Literal["SMS", "Web"] = "SMS"


class CreateTemplate(TemplateFields):
    operation: Literal["create_template"] = _operation("create_template", "Templates", "Create a reusable SMS or web template.")


class UpdateTemplate(TemplateFields):
    operation: Literal["update_template"] = _operation("update_template", "Templates", "Replace a reusable template's name, text and type.")
    template_id: str


class DeleteTemplate(Input):
    operation: Literal["delete_template"] = _operation("delete_template", "Templates", "Delete a reusable template permanently.")
    template_id: str


class ListConversations(Page):
    operation: Literal["list_conversations"] = _operation("list_conversations", "Conversations", "List conversation threads, one page at a time.")


class GetConversation(Input):
    operation: Literal["get_conversation"] = _operation("get_conversation", "Conversations", "Read a conversation thread.")
    conversation_id: str


class CloseConversation(Input):
    operation: Literal["close_conversation"] = _operation("close_conversation", "Conversations", "Close a conversation thread.")
    conversation_id: str


SakariSMSConfig = Annotated[Union[GetAccount, ListContacts, GetContact, CreateContact, UpdateContact,
    DeleteContact, ListMessages, GetMessage, SendMessage, ListTemplates, GetTemplate, CreateTemplate,
    UpdateTemplate, DeleteTemplate, ListConversations, GetConversation, CloseConversation], Field(discriminator="operation")]


class SakariSMSFullConfig(NodeConfig[SakariSMSConfig, SakariSMSAPICredential]):
    pass


# Fixed routes keep user-supplied URLs and methods out of authenticated requests.
ROUTES = {
    "get_account": ("GET", ""),
    "list_contacts": ("GET", "/contacts"), "get_contact": ("GET", "/contacts/{contact_id}"),
    "create_contact": ("POST", "/contacts"), "update_contact": ("PUT", "/contacts/{contact_id}"),
    "delete_contact": ("DELETE", "/contacts/{contact_id}"),
    "list_messages": ("GET", "/messages"), "get_message": ("GET", "/messages/{message_id}"),
    "send_message": ("POST", "/messages"),
    "list_templates": ("GET", "/templates"), "get_template": ("GET", "/templates/{template_id}"),
    "create_template": ("POST", "/templates"), "update_template": ("PUT", "/templates/{template_id}"),
    "delete_template": ("DELETE", "/templates/{template_id}"),
    "list_conversations": ("GET", "/conversations"),
    "get_conversation": ("GET", "/conversations/{conversation_id}"),
    "close_conversation": ("PUT", "/conversations/{conversation_id}/close"),
}


def _redact(value, secrets):
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items()
            if k.lower().replace('_', '') not in {"apicredentials", "clientsecret", "clientid", "accesstoken", "refreshtoken", "authorization"}}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
    return value


def _payload(response):
    if len(response.content) > 5_000_000:
        raise ValueError("Sakari response exceeds the supported size")
    try:
        value = response.json()
    except ValueError:
        raise ValueError("Sakari returned a non-JSON response") from None
    if not isinstance(value, dict):
        raise ValueError("Sakari returned an unexpected response shape")
    return value


class SakariSMSNode(WorkflowNode):
    integration_type = "automation-sakari-sms"
    connection_evidence = ConnectionEvidence(noun="Sakari contacts", operation="list_contacts", label_keys=("email", "firstName", "id"))

    @classmethod
    def get_config_model(cls):
        return SakariSMSFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect Sakari SMS API credentials")
        credential, config = self.config.credentials, self.config.config
        operation = config.operation
        method, path = ROUTES[operation]
        fields = config.model_dump(exclude_none=True)
        path = path.format(**{k: quote(_id(v), safe="") for k, v in fields.items() if k.endswith('_id')})
        params, body = {}, None
        if isinstance(config, Page):
            params = {"offset": config.offset, "limit": config.limit}
        aliases = {"first_name": "firstName", "last_name": "lastName", "contact_id": "contactId", "conversation_id": "conversationId"}
        filters = {"list_contacts": ["first_name", "last_name", "mobile", "email", "tags"],
            "list_messages": ["contact_id", "conversation_id"], "list_templates": ["name"]}
        for key in filters.get(operation, []):
            if key in fields:
                params[aliases.get(key, key)] = fields[key]
        if isinstance(config, ContactFields):
            body = {aliases.get(k, k): fields[k] for k in ["first_name", "last_name", "email", "attributes"] if k in fields}
            body["mobile"] = {"number": config.mobile_number, **({"country": config.country} if config.country else {})}
            if isinstance(config, CreateContact) and config.merge_strategy:
                params["mergeStrategy"] = config.merge_strategy
        elif isinstance(config, TemplateFields):
            body = {"name": config.name, "template": config.template, "type": config.template_type}
        elif isinstance(config, SendMessage):
            body = {"contacts": [{"mobile": {"number": config.mobile_number, **({"country": config.country} if config.country else {})}}],
                "template": config.template, "type": "SMS"}
            if config.group_id:
                body["phoneNumberFilter"] = {"group": {"id": config.group_id}}
        secrets = [credential.client_id, credential.client_secret]
        write = method != "GET"
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                auth_response = await client.post(API + "/oauth2/token", json={"grant_type": "client_credentials",
                    "client_id": credential.client_id, "client_secret": credential.client_secret}, headers={"Accept": "application/json"})
                auth = _payload(auth_response)
                if auth_response.status_code != 200 or auth.get("error"):
                    result = {"status": "error", "success": False, "status_code": auth_response.status_code, "error": auth.get("error", auth)}
                else:
                    token = auth.get("access_token")
                    if not isinstance(token, str) or not token or any(ord(c) < 32 or ord(c) > 126 for c in token) or str(auth.get("token_type", "")).lower() != "bearer":
                        raise ValueError("Sakari returned an incomplete token response")
                    secrets.append(token)
                    kwargs = {"params": params, "headers": {"Authorization": "Bearer " + token, "Accept": "application/json"}}
                    if body is not None:
                        kwargs["json"] = body
                    response = await client.request(method, API + "/v1/accounts/" + quote(credential.account_id, safe="") + path, **kwargs)
                    payload = _payload(response)
                    if not 200 <= response.status_code < 300 or payload.get("success") is False or payload.get("error"):
                        result = {"status": "error", "success": False, "status_code": response.status_code, "error": payload.get("error", payload)}
                    else:
                        if payload.get("success") is not True:
                            raise ValueError("Sakari did not confirm success")
                        if operation.startswith("delete_"):
                            result = {"status": "success", "success": True, "deletion_acknowledged": True}
                        else:
                            data = payload.get("data")
                            expected = list if isinstance(config, Page) or operation in {"create_contact", "create_template"} else dict
                            if not isinstance(data, expected):
                                raise ValueError("Sakari returned an unexpected data shape")
                            if operation == "get_account":
                                data = {k: data[k] for k in ["id", "name", "balance", "externalName", "legalName"] if k in data}
                            result = {"status": "success", "success": True, "data": data}
                            if isinstance(config, Page):
                                pagination = payload.get("pagination")
                                if not isinstance(pagination, dict):
                                    raise ValueError("Sakari did not return page metadata")
                                result["pagination"] = pagination
                            if operation == "send_message":
                                result["delivery_verified"] = False
                        result["status_code"] = response.status_code
        except httpx.TransportError:
            result = {"status": "unknown" if write else "error", "success": False,
                "error": "Sakari request could not complete. Inspect the account before retrying a write."}
        except ValueError:
            result = {"status": "unknown" if write else "error", "success": False,
                "error": "Sakari response could not be verified. Inspect the account before retrying a write."}
        result = _redact(result, secrets)
        await self.emit(result)
        return result
