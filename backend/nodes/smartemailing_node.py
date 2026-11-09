"""SmartEmailing v3 contact, list, template and automation operations.

Uses the provider's username/API-key Basic authentication and fixed API origin.
Each operation makes one documented request; asynchronous acknowledgements never claim delivery.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.smartemailing.cz/api/v3"
DOCS_URL = "https://app.smartemailing.cz/docs/api/v3/index.html"


class SmartEmailingCredential(BaseModel):
    model_config = ConfigDict(title="SmartEmailing API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": DOCS_URL,
            "x-credential-instructions": "Enter your SmartEmailing username and API key from your account's API settings. The key is sent with HTTP Basic authentication. Your account permissions apply to all operations."})
    credential_type: Literal["smartemailing_api_key"] = Field("smartemailing_api_key", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, max_length=320, title="Username")
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("username")
    @classmethod
    def username_valid(cls, value):
        value = value.strip()
        if not value or ":" in value or any(ord(c) < 32 for c in value):
            raise ValueError("Enter your SmartEmailing username without a colon or control characters")
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def key_valid(cls, value):
        return clean_secret(value, field_name="API key")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Page(Input):
    limit: int = Field(100, ge=1, le=500, description="Records in this page, at most 500. This operation fetches one page.")
    offset: int = Field(0, ge=0, description="Records to skip; use next_offset for the next page.")


class ContactListMembership(Input):
    id: int = Field(..., gt=0, title="Contact list ID")
    status: Literal["confirmed", "unsubscribed", "removed"]


class ContactCustomField(Input):
    id: int = Field(..., gt=0)
    value: str | None = None
    options: list[int] | None = None


class Contact(Input):
    emailaddress: EmailStr
    name: str | None = None
    surname: str | None = None
    company: str | None = None
    phone: str | None = None
    cellphone: str | None = None
    country: str | None = None
    language: str | None = None
    notes: str | None = None
    blacklisted: Literal[0, 1] | None = None
    contactlists: list[ContactListMembership] | None = None
    customfields: list[ContactCustomField] | None = None


class ImportSettings(Input):
    update: bool = True
    preserve_unsubscribed: bool = Field(True, description="Keep existing unsubscribed contacts unsubscribed.")
    skip_invalid_emails: bool = False


class Sender(Input):
    from_address: EmailStr = Field(..., alias="from", title="From email", description="Must be a confirmed sender address.")
    reply_to: EmailStr
    sender_name: str = Field(..., min_length=1)


class Recipient(Input):
    emailaddress: EmailStr


class Replacement(Input):
    key: str = Field(..., min_length=1, max_length=50)
    content: str = Field(..., max_length=65536)


class SendTask(Input):
    recipient: Recipient
    replace: list[Replacement] | None = None


class AutomationEvent(Input):
    emailaddress: EmailStr
    name: str = Field(..., min_length=1)
    payload: dict


class SmartEmailingGetAccountInfo(Input):
    """Get account info."""
    operation: Literal["get_account_info"] = Field("get_account_info", json_schema_extra={"ui:hidden": True})


class SmartEmailingListContacts(Page):
    """List contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    emailaddress: EmailStr | None = None
    name: str | None = None
    surname: str | None = None
    expand: Literal["customfields"] | None = None


class SmartEmailingGetContact(Input):
    """Get contact."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    emailaddress: str = Field(..., min_length=1, description="Contact ID or email address.")
    expand: Literal["customfields"] | None = None


class SmartEmailingImportContacts(Input):
    """Insert or update up to 500 contacts, memberships and custom fields."""
    operation: Literal["import_contacts"] = Field("import_contacts", json_schema_extra={"ui:hidden": True})
    data: list[Contact] = Field(..., min_length=1, max_length=500)
    settings: ImportSettings = Field(default_factory=ImportSettings)


class SmartEmailingChangeEmailAddress(Input):
    """Change email address."""
    operation: Literal["change_email_address"] = Field("change_email_address", json_schema_extra={"ui:hidden": True})
    from_address: EmailStr = Field(..., title="Original email")
    to_address: EmailStr = Field(..., title="New email")


class SmartEmailingListContactLists(Page):
    """List contact lists."""
    operation: Literal["list_contact_lists"] = Field("list_contact_lists", json_schema_extra={"ui:hidden": True})


class SmartEmailingGetContactList(Input):
    """Get contact list."""
    operation: Literal["get_contact_list"] = Field("get_contact_list", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., gt=0, title="Resource ID")


class SmartEmailingCreateContactList(Input):
    """Create contact list."""
    operation: Literal["create_contact_list"] = Field("create_contact_list", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    publicname: str | None = None
    sendername: str | None = None
    senderemail: EmailStr | None = None
    replyto: EmailStr | None = None
    @model_validator(mode="after")
    def confirmed_sender_pair(self):
        if any((self.sendername, self.senderemail, self.replyto)) and not (self.senderemail and self.replyto):
            raise ValueError("Sender fields require both confirmed sender email and reply-to")
        return self


class SmartEmailingUpdateContactList(Input):
    """Update contact list."""
    operation: Literal["update_contact_list"] = Field("update_contact_list", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., gt=0, title="Resource ID")
    name: str = Field(..., min_length=1)
    publicname: str | None = None
    sendername: str | None = None
    senderemail: EmailStr | None = None
    replyto: EmailStr | None = None


class SmartEmailingListContactsInList(Input):
    """List contacts in list."""
    operation: Literal["list_contacts_in_list"] = Field("list_contacts_in_list", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., gt=0, title="Resource ID")


class SmartEmailingListCustomFields(Page):
    """List custom fields."""
    operation: Literal["list_custom_fields"] = Field("list_custom_fields", json_schema_extra={"ui:hidden": True})
    expand: Literal["customfield_options"] | None = None


class SmartEmailingGetCustomField(Input):
    """Get custom field."""
    operation: Literal["get_custom_field"] = Field("get_custom_field", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., gt=0, title="Resource ID")


class SmartEmailingCreateCustomField(Input):
    """Create custom field."""
    operation: Literal["create_custom_field"] = Field("create_custom_field", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    type: Literal["text", "textarea", "bool", "numeric", "date", "checkbox", "radio", "select"]


class SmartEmailingListCustomFieldOptions(Page):
    """List custom field options."""
    operation: Literal["list_custom_field_options"] = Field("list_custom_field_options", json_schema_extra={"ui:hidden": True})


class SmartEmailingCreateCustomFieldOption(Input):
    """Create custom field option."""
    operation: Literal["create_custom_field_option"] = Field("create_custom_field_option", json_schema_extra={"ui:hidden": True})
    customfield_id: int = Field(..., gt=0)
    name: str = Field(..., min_length=1)
    order: int


class SmartEmailingListEmails(Page):
    """List emails."""
    operation: Literal["list_emails"] = Field("list_emails", json_schema_extra={"ui:hidden": True})


class SmartEmailingGetEmail(Input):
    """Get email."""
    operation: Literal["get_email"] = Field("get_email", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., gt=0, title="Resource ID")


class SmartEmailingCreateEmail(Input):
    """Create email."""
    operation: Literal["create_email"] = Field("create_email", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1, title="Subject")
    name: str | None = None
    htmlbody: str | None = None
    textbody: str | None = None
    template: Literal[0, 1] = 0
    footer_id: int | None = Field(None, gt=0)
    @model_validator(mode="after")
    def body_required(self):
        if not self.htmlbody and not self.textbody:
            raise ValueError("Provide an HTML or plain text email body")
        return self


class SmartEmailingSendTransactionalEmails(Input):
    """Send transactional emails."""
    operation: Literal["send_transactional_emails"] = Field("send_transactional_emails", json_schema_extra={"ui:hidden": True})
    sender_credentials: Sender
    tag: str = Field(..., min_length=1)
    email_id: int = Field(..., gt=0, description="Existing email/template ID. Transactional sending must be enabled by SmartEmailing support.")
    tasks: list[SendTask] = Field(..., min_length=1, max_length=5, description="Non-advertising transactional messages; sent even to unsubscribed or blacklisted contacts. Acknowledgement means queued, not delivered.")


class SmartEmailingListAutomations(Page):
    """List automations."""
    operation: Literal["list_automations"] = Field("list_automations", json_schema_extra={"ui:hidden": True})
    name: str | None = None


class SmartEmailingGetAutomation(Input):
    """Get automation."""
    operation: Literal["get_automation"] = Field("get_automation", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200)


class SmartEmailingTriggerEvents(Input):
    """Trigger events."""
    operation: Literal["trigger_events"] = Field("trigger_events", json_schema_extra={"ui:hidden": True})
    events: list[AutomationEvent] = Field(..., min_length=1, max_length=500, description="Events without a matching trigger are ignored by the provider.")


class SmartEmailingListNewsletterStatistics(Page):
    """List newsletter statistics."""
    operation: Literal["list_newsletter_statistics"] = Field("list_newsletter_statistics", json_schema_extra={"ui:hidden": True})


SmartEmailingOperation = Annotated[Union[
    SmartEmailingGetAccountInfo,
    SmartEmailingListContacts,
    SmartEmailingGetContact,
    SmartEmailingImportContacts,
    SmartEmailingChangeEmailAddress,
    SmartEmailingListContactLists,
    SmartEmailingGetContactList,
    SmartEmailingCreateContactList,
    SmartEmailingUpdateContactList,
    SmartEmailingListContactsInList,
    SmartEmailingListCustomFields,
    SmartEmailingGetCustomField,
    SmartEmailingCreateCustomField,
    SmartEmailingListCustomFieldOptions,
    SmartEmailingCreateCustomFieldOption,
    SmartEmailingListEmails,
    SmartEmailingGetEmail,
    SmartEmailingCreateEmail,
    SmartEmailingSendTransactionalEmails,
    SmartEmailingListAutomations,
    SmartEmailingGetAutomation,
    SmartEmailingTriggerEvents,
    SmartEmailingListNewsletterStatistics
], Field(discriminator="operation")]


class SmartEmailingConfig(NodeConfig[SmartEmailingOperation, SmartEmailingCredential]):
    pass


OPERATIONS = {
    "get_account_info": ('GET', '/account-info'),
    "list_contacts": ('GET', '/contacts'),
    "get_contact": ('GET', '/contacts/{emailaddress}'),
    "import_contacts": ('POST', '/import'),
    "change_email_address": ('POST', '/change-emailaddress'),
    "list_contact_lists": ('GET', '/contactlists'),
    "get_contact_list": ('GET', '/contactlists/{id}'),
    "create_contact_list": ('POST', '/contactlists'),
    "update_contact_list": ('PUT', '/contactlists/{id}'),
    "list_contacts_in_list": ('GET', '/contactlists/{id}/contacts'),
    "list_custom_fields": ('GET', '/customfields'),
    "get_custom_field": ('GET', '/customfields/{id}'),
    "create_custom_field": ('POST', '/customfields'),
    "list_custom_field_options": ('GET', '/customfield-options'),
    "create_custom_field_option": ('POST', '/customfield-options'),
    "list_emails": ('GET', '/emails'),
    "get_email": ('GET', '/emails/{id}'),
    "create_email": ('POST', '/emails'),
    "send_transactional_emails": ('POST', '/send/transactional-emails-bulk'),
    "list_automations": ('GET', '/automations'),
    "get_automation": ('GET', '/automations/{id}'),
    "trigger_events": ('POST', '/trigger-event'),
    "list_newsletter_statistics": ('GET', '/newsletter-stats-summary'),
}


class SmartEmailingNode(WorkflowNode):
    integration_type = "automation-smartemailing"
    connection_evidence = ConnectionEvidence(noun="contact lists", operation="list_contact_lists",
        identity_operation="get_account_info", identity_keys=("username", "company", "account_id"))

    @classmethod
    def get_config_model(cls):
        return SmartEmailingConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a SmartEmailing username and API key")
        op = self.config.config
        credential = self.config.credentials
        method, route = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True, by_alias=True, exclude={"operation"})
        for field in ("id", "emailaddress"):
            if "{" + field + "}" in route:
                if str(values[field]) in {".", ".."}:
                    raise ValueError("Use a SmartEmailing resource ID or email address")
                route = route.replace("{" + field + "}", quote(str(values.pop(field)), safe=""))
        if op.operation == "change_email_address":
            values = {"from": values["from_address"], "to": values["to_address"]}
        body = values.pop("events") if op.operation == "trigger_events" else values
        kwargs = {"params": values} if method == "GET" else {"json": body}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + route,
                    auth=httpx.BasicAuth(credential.username, credential.api_key),
                    headers={"Accept": "application/json"}, **kwargs)
        except httpx.TransportError:
            raise ValueError("SmartEmailing request could not be confirmed; inspect writes before retrying") from None
        if len(response.content) > 10_000_000:
            raise ValueError("SmartEmailing response exceeds the supported size")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("SmartEmailing returned an unexpected response") from None
        if not isinstance(payload, dict):
            raise ValueError("SmartEmailing returned an unexpected response envelope")
        expected = 200 if method == "GET" else 201 if method == "POST" else 200
        if response.status_code != expected or payload.get("status") != ("created" if expected == 201 else "ok"):
            message = payload.get("message")
            if not isinstance(message, str):
                message = "SmartEmailing request was rejected or could not be confirmed"
            output = {"status": "error", "http_status": response.status_code,
                "message": message.replace(credential.api_key, "[redacted]")}
        else:
            if op.operation == "import_contacts":
                if not isinstance(payload.get("contacts_map"), list) or not isinstance(payload.get("double_opt_in_map"), list):
                    raise ValueError("SmartEmailing import acknowledgement is incomplete; inspect before retrying")
            elif op.operation != "change_email_address":
                expected_type = list if op.operation.startswith("list_") or op.operation == "send_transactional_emails" else dict
                if not isinstance(payload.get("data"), expected_type):
                    raise ValueError("SmartEmailing response data has an unexpected shape")
            output = {**payload, "provider_status": payload["status"], "status": "success",
                "http_status": response.status_code}
            if isinstance(op, Page) and isinstance(payload.get("data"), list):
                meta = payload.get("meta")
                total = meta.get("total_count") if isinstance(meta, dict) else None
                next_offset = op.offset + len(payload["data"])
                output["next_offset"] = next_offset if type(total) is int and next_offset < total and next_offset > op.offset else None
            if op.operation == "send_transactional_emails":
                output.update(queued=True, delivery_verified=False)
            if op.operation == "trigger_events":
                output["automation_completion_verified"] = False
        await self.emit(output)
        return output
