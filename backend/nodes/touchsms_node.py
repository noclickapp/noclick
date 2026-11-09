"""touchSMS API v2 operations, pinned to the provider's published 2.0.0 contract.

Each operation makes one request. Lists return one page and the provider's
pagination envelope; messages report acceptance, never delivery confirmation.
"""
from __future__ import annotations

import base64
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import AnyHttpUrl, AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, StrictInt, StrictStr, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.touchsms.com.au/api"


class TouchSMSCredential(BaseModel):
    model_config = ConfigDict(
        title="touchSMS API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dev.touchsms.com.au/get-started/quickstart/",
            "x-credential-instructions": "In touchSMS, open Settings → API Keys and copy both the Access Token and Token ID. NoClick uses the Access Token as the HTTP Basic username and the Token ID as the password. Connection testing reads your account details without sending a message.",
        },
    )
    credential_type: Literal["touchsms_api_key"] = Field("touchsms_api_key", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})
    token_id: str = Field(..., title="Token ID", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", "token_id", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() for c in value) or ":" in value:
            raise ValueError("Paste only the token value, without a header or colon")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)


ID = Annotated[int, Field(ge=1)]


class GetAccount(Input):
    """Read the account and credit balance belonging to the API key."""
    operation: Literal["get_account"] = "get_account"


class Page(Input):
    page: int = Field(1, ge=1, description="Page number. Use the returned links and meta to determine whether another page exists. One page is returned per execution.")


class SearchPage(Page):
    search: str | None = None


class ListGroups(SearchPage):
    operation: Literal["list_groups"] = "list_groups"
    sort_by: Literal["name", "created"] = "name"
    sort_order: Literal["asc", "desc"] = "asc"
    per_page: int = Field(50, ge=10, le=200)


class GetGroup(Input):
    operation: Literal["get_group"] = "get_group"
    group_id: ID


class ListContacts(SearchPage):
    operation: Literal["list_contacts"] = "list_contacts"
    sort_by: Literal["id", "firstname", "surname", "created"] = "firstname"
    sort_order: Literal["asc", "desc"] = "asc"
    per_page: int = Field(50, ge=10, le=200)


class GetContact(Input):
    operation: Literal["get_contact"] = "get_contact"
    contact_id: ID


class ContactBody(Input):
    number: str = Field(..., min_length=5, max_length=20, description="Mobile number, preferably in E.164 format.")
    firstname: str | None = None
    surname: str | None = None
    email: EmailStr | None = None
    group: str | None = Field(None, description="Group name. touchSMS creates the group if necessary.")
    groups: list[int] | None = Field(None, description="Group IDs to add this contact to.")
    metadata: dict[str, Any] | None = Field(None, description="Custom fields already configured on the account.")


class CreateContact(ContactBody):
    operation: Literal["create_contact"] = "create_contact"
    update_if_exists: bool = Field(False, description="Update a matching number instead of creating a duplicate.")


class UpdateContact(ContactBody):
    """Update the contact; the API requires its number even for a name change."""
    operation: Literal["update_contact"] = "update_contact"
    contact_id: ID


class DeleteContact(GetContact):
    """Permanently delete the selected contact."""
    operation: Literal["delete_contact"] = "delete_contact"


class ListTemplates(Input):
    operation: Literal["list_templates"] = "list_templates"


class GetTemplate(Input):
    operation: Literal["get_template"] = "get_template"
    template_id: ID


class TemplateBody(Input):
    sender_id: str = Field(..., min_length=1, description="An allowed sender ID, such as SHARED_NUMBER.")
    name: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1, description="Template text. Merge fields are not filled in automatically when sending.")
    subject: str | None = Field(None, max_length=40, description="MMS subject. Null clears the subject on update.")


class CreateTemplate(TemplateBody):
    operation: Literal["create_template"] = "create_template"


class UpdateTemplate(TemplateBody):
    """Replace a template using the complete required sender, name and message."""
    operation: Literal["update_template"] = "update_template"
    template_id: ID


class DeleteTemplate(GetTemplate):
    operation: Literal["delete_template"] = "delete_template"


class ListOptouts(SearchPage):
    operation: Literal["list_optouts"] = "list_optouts"


class GetOptout(Input):
    operation: Literal["get_optout"] = "get_optout"
    optout_id: ID


class OptoutSelection(Input):
    opt_out_list_id: int | None = None
    opt_out_list_name: str | None = Field(None, max_length=255)

    @model_validator(mode="after")
    def exclusive_list(self):
        if self.opt_out_list_id is not None and self.opt_out_list_name is not None:
            raise ValueError("Choose either an opt-out list ID or name, not both")
        return self


class CreateOptout(OptoutSelection):
    """Stop messages to a number; creates a named opt-out list if needed."""
    operation: Literal["create_optout"] = "create_optout"
    number: str = Field(..., min_length=1)


class DeleteOptout(GetOptout):
    """Remove the opt-out so this number can receive messages again."""
    operation: Literal["delete_optout"] = "delete_optout"


class ListOptoutLists(Input):
    operation: Literal["list_optout_lists"] = "list_optout_lists"


class GetOptoutList(Input):
    operation: Literal["get_optout_list"] = "get_optout_list"
    optout_list_id: ID


class ListOptoutListOptouts(SearchPage):
    operation: Literal["list_optout_list_optouts"] = "list_optout_list_optouts"
    optout_list_id: ID


class ListSenderIds(Input):
    operation: Literal["list_sender_ids"] = "list_sender_ids"
    country: str | None = Field(None, min_length=2, max_length=3)
    message_type: Literal["sms", "mms"] = "sms"


class ListSenderIdsForNumber(Input):
    operation: Literal["list_sender_ids_for_number"] = "list_sender_ids_for_number"
    number: str = Field(..., min_length=1, max_length=30)
    message_type: Literal["sms", "mms"] = "sms"


class ListInbounds(Page):
    operation: Literal["list_inbounds"] = "list_inbounds"
    created_after: AwareDatetime | None = None
    id_after: int | None = None


class OutgoingMessage(Input):
    to: str = Field(..., min_length=1, description="Recipient number, preferably E.164.")
    from_: str = Field(..., alias="from", min_length=1, description="An allowed sender ID or SHARED_NUMBER.")
    body: str | None = Field(None, max_length=1600)
    campaign: str | None = Field(None, max_length=190)
    reference: str | None = Field(None, max_length=190)
    metadata: dict[str, StrictStr | StrictInt] | None = None
    media: list[AnyHttpUrl] | None = Field(None, max_length=1, description="One public image URL (JPEG, PNG or GIF, up to 1MB), sent from an MMS-enabled dedicated number.")
    date: AwareDatetime | None = Field(None, description="Schedule time as an ISO 8601 UTC timestamp.")

    @field_validator("metadata")
    @classmethod
    def metadata_limits(cls, value):
        if value is not None:
            if len(value) > 10 or any(len(k) > 50 or len(str(v)) > 100 for k, v in value.items()):
                raise ValueError("Use up to 10 metadata entries with 50-character keys and 100-character values")
            if len(str(value.get("mms_subject", ""))) > 40:
                raise ValueError("MMS subject must be at most 40 characters")
        return value

    @model_validator(mode="after")
    def content_required(self):
        if not self.body and not self.media:
            raise ValueError("Provide message text or one media URL")
        return self


class SendMessages(OptoutSelection):
    """Send SMS or MMS. Inspect data.errors for rejected messages; acceptance is not delivery."""
    operation: Literal["send_messages"] = "send_messages"
    messages: list[OutgoingMessage] = Field(..., min_length=1, max_length=1000)
    reject_duplicates: bool = False
    reject_duplicates_by_recipient: bool = False


class ValidateMessages(SendMessages):
    """Validate and price messages without sending anything."""
    operation: Literal["validate_messages"] = "validate_messages"


TouchSMSConfig = Annotated[Union[
    GetAccount, ListGroups, GetGroup, ListContacts, GetContact, CreateContact,
    UpdateContact, DeleteContact, ListTemplates, GetTemplate, CreateTemplate,
    UpdateTemplate, DeleteTemplate, ListOptouts, GetOptout, CreateOptout,
    DeleteOptout, ListOptoutLists, GetOptoutList, ListOptoutListOptouts,
    ListSenderIds, ListSenderIdsForNumber, ListInbounds, SendMessages, ValidateMessages,
], Field(discriminator="operation")]


class TouchSMSFullConfig(NodeConfig[TouchSMSConfig, TouchSMSCredential]):
    pass


# One public operation corresponds to exactly one provider operation.
ROUTES = {
    "get_account": ("GET", "/v2/account"),
    "list_groups": ("GET", "/v2/groups"),
    "get_group": ("GET", "/v2/groups/{group_id}"),
    "list_contacts": ("GET", "/v2/contacts"),
    "get_contact": ("GET", "/v2/contacts/{contact_id}"),
    "create_contact": ("POST", "/v2/contacts"),
    "update_contact": ("PUT", "/v2/contacts/{contact_id}"),
    "delete_contact": ("DELETE", "/v2/contacts/{contact_id}"),
    "list_templates": ("GET", "/v2/templates"),
    "get_template": ("GET", "/v2/templates/{template_id}"),
    "create_template": ("POST", "/v2/templates"),
    "update_template": ("PUT", "/v2/templates/{template_id}"),
    "delete_template": ("DELETE", "/v2/templates/{template_id}"),
    "list_optouts": ("GET", "/v2/optouts"),
    "get_optout": ("GET", "/v2/optouts/{optout_id}"),
    "create_optout": ("POST", "/v2/optouts"),
    "delete_optout": ("DELETE", "/v2/optouts/{optout_id}"),
    "list_optout_lists": ("GET", "/v2/optout-lists"),
    "get_optout_list": ("GET", "/v2/optout-lists/{optout_list_id}"),
    "list_optout_list_optouts": ("GET", "/v2/optout-lists/{optout_list_id}/optouts"),
    "list_sender_ids": ("GET", "/v2/account/sender-ids"),
    "list_sender_ids_for_number": ("GET", "/v2/account/sender-ids/for/{number}"),
    "list_inbounds": ("GET", "/v2/inbounds"),
    "send_messages": ("POST", "/v2/sms"),
    "validate_messages": ("POST", "/v2/sms/dry"),
}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    return value


class TouchSMSNode(WorkflowNode):
    integration_type = "automation-touchsms"
    connection_evidence = ConnectionEvidence(
        noun="touchSMS account", identity_operation="get_account",
        identity_keys=("full_name", "email", "firstname"),
    )

    @classmethod
    def get_config_model(cls):
        return TouchSMSFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a touchSMS API key")
        op, credential = self.config.config, self.config.credentials
        action = op.operation
        method, path = ROUTES[action]
        values = op.model_dump(mode="json", by_alias=True, exclude_none=True, exclude={"operation"})
        # A null subject is documented and clears an existing MMS subject.
        if isinstance(op, TemplateBody) and "subject" in op.model_fields_set:
            values["subject"] = op.subject
        for field in type(op).model_fields:
            marker = "{" + field + "}"
            if marker in path:
                path = path.replace(marker, quote(str(values.pop(field)), safe=""))
        basic = base64.b64encode(f"{credential.access_token}:{credential.token_id}".encode()).decode("ascii")
        secrets = (credential.access_token, credential.token_id, basic)
        headers = {"Authorization": "Basic " + basic, "Accept": "application/json"}
        kwargs = {"params": values} if method == "GET" else {"json": values} if method != "DELETE" else {}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, headers=headers, **kwargs)
        except httpx.RequestError:
            # A failed write transport may have reached the provider. Never retry it.
            output = {"status": "error", "error": "touchSMS request did not complete", "write_outcome": "unknown" if method != "GET" else None}
        else:
            output = self._parse_response(action, method, response)
        output = _redact(output, secrets)
        await self.emit(output)
        return output

    @staticmethod
    def _parse_response(action, method, response):
        status = response.status_code
        expected = {204} if action in {"delete_contact", "delete_template"} else {200} if action == "delete_optout" else {200, 201} if action in {"create_contact", "create_optout"} else {201} if action == "create_template" else {200}
        if status not in expected:
            message = "touchSMS request failed"
            try:
                body = response.json()
                if isinstance(body, dict) and isinstance(body.get("message"), str):
                    message = body["message"]
            except ValueError:
                pass
            return {"status": "error", "error": message, "http_status": status}
        if method == "DELETE":
            return {"status": "success", "http_status": status, "deletion_acknowledged": True}
        try:
            if len(response.content) > 10_000_000 or "json" not in response.headers.get("content-type", "").lower():
                raise ValueError("Expected bounded JSON")
            body = response.json()
            expected_type = list if action.startswith("list_") else dict
            if not isinstance(body, dict) or not isinstance(body.get("data"), expected_type):
                raise ValueError("Missing data envelope")
        except (ValueError, TypeError):
            return {"status": "error", "error": "touchSMS returned an unexpected response", "http_status": status, "write_outcome": "unknown" if method != "GET" else None}
        if action == "get_account" and (type(body["data"].get("id")) is not int or not any(isinstance(body["data"].get(k), str) and body["data"][k].strip() for k in ("full_name", "email", "firstname"))):
            return {"status": "error", "error": "touchSMS account identity was missing", "http_status": status}
        output = {**body, "status": "success", "http_status": status}
        if action in {"send_messages", "validate_messages"}:
            data = body["data"]
            if not isinstance(data.get("messages"), list) or not isinstance(data.get("errors"), list):
                return {"status": "error", "error": "touchSMS message results were incomplete", "http_status": status}
            output.update({"all_accepted": not data["errors"], "delivery_verified": False, "dry_run": action == "validate_messages"})
            if data["errors"]:
                output["status"] = "partial" if data["messages"] else "error"
                output["message" if data["messages"] else "error"] = "Some messages were rejected; inspect data.errors before retrying"
        return output
