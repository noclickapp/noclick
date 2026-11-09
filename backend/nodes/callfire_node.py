"""CallFire V2 operations. Contract: https://www.callfire.com/v2/api-docs/swagger.json.

API login/password are generated in CallFire's API Access settings, not the
person's account sign-in password. Each operation issues one fixed API request.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.callfire.com/v2"


class CallFireCredential(BaseModel):
    model_config = ConfigDict(title="Callfire API Login", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.callfire.com/developers/manage/access",
            "x-credential-instructions": "In CallFire Settings → API Access, create API credentials and paste the API login and API password. Use API credentials, not your CallFire account sign-in password. NoClick reads your account details to verify the connection.",
        })
    credential_type: Literal["callfire_api_credentials"] = Field("callfire_api_credentials", json_schema_extra={"ui:hidden": True})
    api_login: str = Field(..., min_length=1, max_length=512, title="API login", json_schema_extra={"ui:widget": "password"})
    api_password: str = Field(..., min_length=1, max_length=512, title="API password", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_login", "api_password", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() for c in value) or (info.field_name == "api_login" and ":" in value):
            raise ValueError("Paste the API credential without whitespace or an authentication header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    limit: int = Field(100, ge=1, le=1000, description="Maximum records in this page; use offset for subsequent pages.")
    offset: int = Field(0, ge=0, le=2147483647)


class _Id(_Input):
    id: int = Field(..., gt=0, le=9223372036854775807, title="Resource ID")


Phone = Annotated[str, Field(pattern=r"^[0-9]{5,11}$", description="CallFire phone number: 11 digits including country code, or a short code; no plus sign.")]


class Contact(_Input):
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    mobilePhone: Optional[Phone] = None
    homePhone: Optional[Phone] = None
    workPhone: Optional[Phone] = None
    zipcode: Optional[str] = None
    externalId: Optional[str] = None
    externalSystem: Optional[Literal["NATION_BUILDER", "SALES_FORCE_CONTACTS", "SALES_FORCE_LEADS", "SALES_FORCE_REPORTS"]] = None
    properties: Optional[dict[str, str]] = None


class TextRecipient(_Input):
    phoneNumber: Phone
    message: Optional[str] = Field(None, min_length=1)
    fromNumber: Optional[Phone] = None
    attributes: Optional[dict[str, str]] = None


class CallRecipient(_Input):
    phoneNumber: Phone
    fromNumber: Optional[Phone] = Field(None, description="A verified CallFire caller ID; omit to use the campaign caller ID. Sufficient credits are required.")
    liveMessage: str = Field(..., min_length=1)
    machineMessage: Optional[str] = None
    voice: Optional[Literal["MALE1", "FEMALE1", "FEMALE2", "SPANISH1", "FRENCHCANADIAN1"]] = None
    attributes: Optional[dict[str, str]] = None


class GetAccount(_Input):
    operation: Literal["get_account"] = "get_account"


class ListTexts(_Page):
    operation: Literal["list_texts"] = "list_texts"
    inbound: Optional[bool] = None
    toNumber: Optional[Phone] = None
    fromNumber: Optional[Phone] = None


class GetText(_Id):
    operation: Literal["get_text"] = "get_text"


class SendTexts(_Input):
    operation: Literal["send_texts"] = "send_texts"
    recipients: list[TextRecipient] = Field(..., min_length=1, max_length=100)
    defaultMessage: Optional[str] = Field(None, min_length=1)
    campaignId: Optional[int] = Field(None, gt=0)

    @model_validator(mode="after")
    def messages(self):
        if not self.defaultMessage and any(not r.message for r in self.recipients):
            raise ValueError("Provide a message for each recipient or a default message")
        return self


class ListCalls(_Page):
    operation: Literal["list_calls"] = "list_calls"
    inbound: Optional[bool] = None
    toNumber: Optional[Phone] = None
    fromNumber: Optional[Phone] = None


class GetCall(_Id):
    operation: Literal["get_call"] = "get_call"


class SendCalls(_Input):
    operation: Literal["send_calls"] = "send_calls"
    recipients: list[CallRecipient] = Field(..., min_length=1, max_length=10)
    campaignId: Optional[int] = Field(None, gt=0)


class ListContacts(_Page):
    operation: Literal["list_contacts"] = "list_contacts"


class GetContact(_Id):
    operation: Literal["get_contact"] = "get_contact"


class CreateContacts(_Input):
    operation: Literal["create_contacts"] = "create_contacts"
    contacts: list[Contact] = Field(..., min_length=1, max_length=100)

    @model_validator(mode="after")
    def phones(self):
        if any(not (c.mobilePhone or c.homePhone or c.workPhone) for c in self.contacts):
            raise ValueError("Each new contact needs a phone number")
        return self


class UpdateContact(_Id):
    operation: Literal["update_contact"] = "update_contact"
    contact: Contact


class DeleteContact(_Id):
    operation: Literal["delete_contact"] = "delete_contact"


class ListContactLists(_Page):
    operation: Literal["list_contact_lists"] = "list_contact_lists"
    name: Optional[str] = None


class GetContactList(_Id):
    operation: Literal["get_contact_list"] = "get_contact_list"


class CreateContactList(_Input):
    operation: Literal["create_contact_list"] = "create_contact_list"
    name: str = Field(..., min_length=1)
    contactIds: list[Annotated[int, Field(gt=0)]] = Field(..., min_length=1, max_length=1000)


class UpdateContactList(_Id):
    operation: Literal["update_contact_list"] = "update_contact_list"
    name: str = Field(..., min_length=1)


class DeleteContactList(_Id):
    operation: Literal["delete_contact_list"] = "delete_contact_list"


class ListContactListItems(_Page):
    operation: Literal["list_contact_list_items"] = "list_contact_list_items"
    id: int = Field(..., gt=0, le=9223372036854775807, title="Contact list ID")


class AddContactListItems(_Id):
    operation: Literal["add_contact_list_items"] = "add_contact_list_items"
    contactIds: list[Annotated[int, Field(gt=0)]] = Field(..., min_length=1, max_length=1000)


class ListTextBroadcasts(_Page):
    operation: Literal["list_text_broadcasts"] = "list_text_broadcasts"
    name: Optional[str] = None


class GetTextBroadcast(_Id):
    operation: Literal["get_text_broadcast"] = "get_text_broadcast"


class CreateTextBroadcast(_Input):
    operation: Literal["create_text_broadcast"] = "create_text_broadcast"
    name: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    fromNumber: Phone
    recipients: list[TextRecipient] = Field(..., min_length=1, max_length=100)


class StartTextBroadcast(_Id):
    operation: Literal["start_text_broadcast"] = "start_text_broadcast"


class StopTextBroadcast(_Id):
    operation: Literal["stop_text_broadcast"] = "stop_text_broadcast"


CallFireConfig = Annotated[Union[
    GetAccount, ListTexts, GetText, SendTexts, ListCalls, GetCall, SendCalls,
    ListContacts, GetContact, CreateContacts, UpdateContact, DeleteContact,
    ListContactLists, GetContactList, CreateContactList, UpdateContactList,
    DeleteContactList, ListContactListItems, AddContactListItems,
    ListTextBroadcasts, GetTextBroadcast, CreateTextBroadcast,
    StartTextBroadcast, StopTextBroadcast,
], Field(discriminator="operation")]


class CallFireFullConfig(NodeConfig[CallFireConfig, CallFireCredential]):
    pass


# One node operation maps to exactly one provider operation, never a workflow
# that makes prerequisite, readback, credential-management or billing requests.
ROUTES = {
    "get_account": ("GET", "/me/account"),
    "list_texts": ("GET", "/texts"), "get_text": ("GET", "/texts/{id}"), "send_texts": ("POST", "/texts"),
    "list_calls": ("GET", "/calls"), "get_call": ("GET", "/calls/{id}"), "send_calls": ("POST", "/calls"),
    "list_contacts": ("GET", "/contacts"), "get_contact": ("GET", "/contacts/{id}"),
    "create_contacts": ("POST", "/contacts"), "update_contact": ("PUT", "/contacts/{id}"), "delete_contact": ("DELETE", "/contacts/{id}"),
    "list_contact_lists": ("GET", "/contacts/lists"), "get_contact_list": ("GET", "/contacts/lists/{id}"),
    "create_contact_list": ("POST", "/contacts/lists"), "update_contact_list": ("PUT", "/contacts/lists/{id}"),
    "delete_contact_list": ("DELETE", "/contacts/lists/{id}"),
    "list_contact_list_items": ("GET", "/contacts/lists/{id}/items"), "add_contact_list_items": ("POST", "/contacts/lists/{id}/items"),
    "list_text_broadcasts": ("GET", "/texts/broadcasts"), "get_text_broadcast": ("GET", "/texts/broadcasts/{id}"),
    "create_text_broadcast": ("POST", "/texts/broadcasts"),
    "start_text_broadcast": ("POST", "/texts/broadcasts/{id}/start"), "stop_text_broadcast": ("POST", "/texts/broadcasts/{id}/stop"),
}


class CallFireNode(WorkflowNode):
    integration_type = "automation-callfire"
    credential_provider_labels = {"callfire": "CallFire"}
    connection_evidence = ConnectionEvidence(noun="CallFire account", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return CallFireFullConfig

    async def execute(self, inputs):
        op = self.config.config
        cred = self.config.credentials
        if not cred:
            return {"status": "error", "error": "Connect CallFire API credentials"}
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        if "id" in values:
            path = path.format(id=values.pop("id"))
        params, body = {}, None
        if method == "GET":
            params = values
            if op.operation == "get_account":
                params = {"fields": "id,name,companyName"}
        elif op.operation in {"send_texts", "send_calls"}:
            body = values["recipients"]
            params = {"strictValidation": "true", **{k: v for k, v in values.items() if k != "recipients"}}
        elif op.operation == "create_contacts":
            body = values["contacts"]
        elif op.operation == "update_contact":
            body = values["contact"]
        elif values:
            body = values
            if op.operation == "create_text_broadcast":
                params = {"start": "false", "strictValidation": "true"}
        # Booleans must be lowercase on the wire, including list filters.
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    auth=httpx.BasicAuth(cred.api_login, cred.api_password),
                    headers={"Accept": "application/json"}, **({"json": body} if body is not None else {}))
            if not 200 <= response.status_code < 300:
                message = "CallFire request rejected"
                try:
                    error = response.json()
                    if isinstance(error, dict) and isinstance(error.get("message"), str):
                        message = error["message"]
                except ValueError:
                    pass
                for secret in (cred.api_login, cred.api_password):
                    message = message.replace(secret, "[redacted]")
                return {"status": "error", "error": message, "http_status": response.status_code}
            if not response.content:
                if op.operation not in {"update_contact", "delete_contact", "update_contact_list", "delete_contact_list", "add_contact_list_items", "start_text_broadcast", "stop_text_broadcast"}:
                    raise ValueError("Expected a CallFire response body")
                return {"status": "success", "http_status": response.status_code, "data": None}
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Expected a CallFire JSON object")
            if data.get("httpStatusCode", 200) >= 400:
                raise ValueError("CallFire returned an error response")
            if op.operation == "get_account":
                if not data.get("id") or not data.get("name"):
                    raise ValueError("CallFire account response has no identity")
                data = {key: data[key] for key in ("id", "name", "companyName") if key in data}
            result = {"status": "success", "data": data, "http_status": response.status_code}
            if isinstance(op, _Page):
                # Expose the provider page unchanged, with an explicit continuation.
                total = data.get("totalCount")
                items = data.get("items", [])
                if not isinstance(items, list):
                    raise ValueError("Expected CallFire page items")
                next_offset = op.offset + len(items)
                result["next_offset"] = next_offset if items and (next_offset < total if isinstance(total, int) else len(items) == op.limit) else None
            return result
        except (httpx.RequestError, ValueError):
            return {"status": "error", "error": "CallFire request could not be confirmed; inspect the provider before retrying a write"}
