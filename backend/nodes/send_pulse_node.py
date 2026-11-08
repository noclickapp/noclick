"""SendPulse bulk email API, pinned to its published OpenAPI 1.0.0 contract."""
from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

class SendPulseAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="SendPulse API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://login.sendpulse.com/settings/api",
        "x-credential-instructions": "Paste the long-lived API key from SendPulse account settings. NoClick sends it as a Bearer token to api.sendpulse.com. This is not the OAuth client secret or a one-hour access token."})
    credential_type: Literal["send_pulse_api_key"] = Field("send_pulse_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Page(Input):
    limit: int = Field(100, ge=1, le=100, description="Records in this page; use offset to retrieve subsequent pages.")
    offset: int = Field(0, ge=0)

class Identifier(Input):
    id: int = Field(..., gt=0, title="Resource ID")

class CreateList(Input):
    bookName: str = Field(..., min_length=1, title="Mailing List Name")

class RenameList(Identifier):
    name: str = Field(..., min_length=1, title="New Name")

class ContactPage(Identifier, Page):
    order: Literal["asc", "desc"] = "asc"
    active: bool | None = None
    not_active: bool | None = None

class Contact(BaseModel):
    email: str = Field(..., min_length=3)
    variables: dict[str, str | int | float] | None = None

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        import re
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value

class AddContacts(Identifier):
    emails: list[Contact] = Field(..., min_length=1, max_length=100, description="Contacts to add using single opt-in. Supply only contacts who consented.")

class Contacts(Identifier):
    emails: list[str] = Field(..., min_length=1, max_length=100)

    @field_validator("emails")
    @classmethod
    def email_formats(cls, values):
        return [Contact.email_format(value) for value in values]

class Templates(Page):
    owner: Literal["me", "sendpulse"] = "me"
    only_active: bool | None = None

class Tag(Input):
    name: str = Field(..., min_length=1)
    color: str = Field(..., pattern=r"^#[0-9a-fA-F]{6}$")

class UpdateTag(Tag, Identifier):
    pass

class ListMailingListsConfig(Page):
    operation: Literal["list_mailing_lists"] = Field("list_mailing_lists", title="List Mailing Lists", json_schema_extra={"ui:hidden": True})

class GetMailingListConfig(Identifier):
    operation: Literal["get_mailing_list"] = Field("get_mailing_list", title="Get Mailing List", json_schema_extra={"ui:hidden": True})

class CreateMailingListConfig(CreateList):
    operation: Literal["create_mailing_list"] = Field("create_mailing_list", title="Create Mailing List", json_schema_extra={"ui:hidden": True})

class RenameMailingListConfig(RenameList):
    operation: Literal["rename_mailing_list"] = Field("rename_mailing_list", title="Rename Mailing List", json_schema_extra={"ui:hidden": True})

class DeleteMailingListConfig(Identifier):
    operation: Literal["delete_mailing_list"] = Field("delete_mailing_list", title="Delete Mailing List", json_schema_extra={"ui:hidden": True})

class ListContactsConfig(ContactPage):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})

class AddContactsConfig(AddContacts):
    operation: Literal["add_contacts"] = Field("add_contacts", title="Add Contacts", json_schema_extra={"ui:hidden": True})

class DeleteContactsConfig(Contacts):
    operation: Literal["delete_contacts"] = Field("delete_contacts", title="Delete Contacts", json_schema_extra={"ui:hidden": True})

class UnsubscribeContactsConfig(Contacts):
    operation: Literal["unsubscribe_contacts"] = Field("unsubscribe_contacts", title="Unsubscribe Contacts", json_schema_extra={"ui:hidden": True})

class GetContactCountConfig(Identifier):
    operation: Literal["get_contact_count"] = Field("get_contact_count", title="Get Contact Count", json_schema_extra={"ui:hidden": True})

class ListVariablesConfig(Identifier):
    operation: Literal["list_variables"] = Field("list_variables", title="List Variables", json_schema_extra={"ui:hidden": True})

class ListCampaignsConfig(Page):
    operation: Literal["list_campaigns"] = Field("list_campaigns", title="List Campaigns", json_schema_extra={"ui:hidden": True})

class GetCampaignConfig(Identifier):
    operation: Literal["get_campaign"] = Field("get_campaign", title="Get Campaign", json_schema_extra={"ui:hidden": True})

class CancelCampaignConfig(Identifier):
    operation: Literal["cancel_campaign"] = Field("cancel_campaign", title="Cancel Campaign", json_schema_extra={"ui:hidden": True})

class ListTemplatesConfig(Templates):
    operation: Literal["list_templates"] = Field("list_templates", title="List Templates", json_schema_extra={"ui:hidden": True})

class ListSendersConfig(Input):
    operation: Literal["list_senders"] = Field("list_senders", title="List Senders", json_schema_extra={"ui:hidden": True})

class ListTagsConfig(Input):
    operation: Literal["list_tags"] = Field("list_tags", title="List Tags", json_schema_extra={"ui:hidden": True})

class CreateTagConfig(Tag):
    operation: Literal["create_tag"] = Field("create_tag", title="Create Tag", json_schema_extra={"ui:hidden": True})

class UpdateTagConfig(UpdateTag):
    operation: Literal["update_tag"] = Field("update_tag", title="Update Tag", json_schema_extra={"ui:hidden": True})

class DeleteTagConfig(Identifier):
    operation: Literal["delete_tag"] = Field("delete_tag", title="Delete Tag", json_schema_extra={"ui:hidden": True})

class GetBalanceConfig(Input):
    operation: Literal["get_balance"] = Field("get_balance", title="Get Balance", json_schema_extra={"ui:hidden": True})

SendPulseConfig = Annotated[Union[ListMailingListsConfig, GetMailingListConfig, CreateMailingListConfig, RenameMailingListConfig, DeleteMailingListConfig, ListContactsConfig, AddContactsConfig, DeleteContactsConfig, UnsubscribeContactsConfig, GetContactCountConfig, ListVariablesConfig, ListCampaignsConfig, GetCampaignConfig, CancelCampaignConfig, ListTemplatesConfig, ListSendersConfig, ListTagsConfig, CreateTagConfig, UpdateTagConfig, DeleteTagConfig, GetBalanceConfig], Field(discriminator="operation")]

class SendPulseFullConfig(NodeConfig[SendPulseConfig, SendPulseAPIKeyCredential]):
    pass

ROUTES = {'list_mailing_lists': ('GET', '/addressbooks'), 'get_mailing_list': ('GET', '/addressbooks/{id}'), 'create_mailing_list': ('POST', '/addressbooks'), 'rename_mailing_list': ('PUT', '/addressbooks/{id}'), 'delete_mailing_list': ('DELETE', '/addressbooks/{id}'), 'list_contacts': ('GET', '/addressbooks/{id}/emails'), 'add_contacts': ('POST', '/addressbooks/{id}/emails'), 'delete_contacts': ('DELETE', '/addressbooks/{id}/emails'), 'unsubscribe_contacts': ('POST', '/addressbooks/{id}/emails/unsubscribe'), 'get_contact_count': ('GET', '/addressbooks/{id}/emails/total'), 'list_variables': ('GET', '/addressbooks/{id}/variables'), 'list_campaigns': ('GET', '/campaigns'), 'get_campaign': ('GET', '/campaigns/{id}'), 'cancel_campaign': ('DELETE', '/campaigns/{id}'), 'list_templates': ('GET', '/templates'), 'list_senders': ('GET', '/senders'), 'list_tags': ('GET', '/tags'), 'create_tag': ('POST', '/tags'), 'update_tag': ('PUT', '/tags/{id}'), 'delete_tag': ('DELETE', '/tags/{id}'), 'get_balance': ('GET', '/balance')}

class SendPulseNode(WorkflowNode):
    integration_type = "automation-send-pulse"
    connection_evidence = ConnectionEvidence(noun="mailing lists", operation="list_mailing_lists")

    @classmethod
    def get_config_model(cls):
        return SendPulseFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a SendPulse API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            path = path.replace("{id}", str(values.pop("id")))
        kwargs = {"params": values} if method == "GET" else ({"json": values} if values else {})
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://api.sendpulse.com" + path,
                    headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}, **kwargs)
        except httpx.HTTPError:
            raise ValueError("SendPulse request failed; inspect the account before retrying a write") from None
        if response.status_code >= 400:
            # Never return request headers or credentials in a transport exception.
            raise ValueError(f"SendPulse HTTP {response.status_code}")
        try:
            body = response.json()
        except (ValueError, UnicodeDecodeError):
            raise ValueError("SendPulse returned an invalid JSON response") from None
        if isinstance(body, dict) and (body.get("result") is False or body.get("error_code") or body.get("error")):
            message = str(body.get("message") or body.get("error") or "SendPulse rejected this request")
            raise ValueError(message.replace(credential.api_key, "[redacted]"))
        if not isinstance(body, (dict, list)):
            raise ValueError("SendPulse returned an unexpected response")
        # Preserve native JSON, including asynchronous tag queue acknowledgements.
        def redact(value):
            if isinstance(value, str):
                return value.replace(credential.api_key, "[redacted]")
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {redact(key): redact(item) for key, item in value.items()}
            return value
        body = redact(body)
        result = {"data": body, "http_status": response.status_code}
        if method == "GET" and "limit" in values and isinstance(body, list):
            result["next_offset"] = values.get("offset", 0) + len(body) if len(body) == values["limit"] else None
        return result
