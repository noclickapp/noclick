"""Project Broadcast API v1 contacts, campaigns and messaging.

Each action sends one documented request using a person's pasted API key.
Searches return one page and preserve the provider's paging metadata.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.projectbroadcast.com/api/v1"


class ProjectBroadcastAPIKey(BaseModel):
    model_config = ConfigDict(title="Project Broadcast API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.projectbroadcast.com/account/security/api-keys",
            "x-credential-instructions": "Create an API key in Project Broadcast under Account → Security → API Keys, then paste it here. NoClick verifies the account using the API key test endpoint.",
        })
    credential_type: Literal["project_broadcast_api_key"] = Field("project_broadcast_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def valid_path_value(cls, value, info):
        if value is not None and info.field_name in {"contact_id", "campaign_id", "custom_field_id", "contact", "tag"}:
            if not isinstance(value, str) or not value.strip() or len(value) > 500 or value in {".", ".."} or re.search(r"[\x00-\x1f\x7f]", value):
                raise ValueError("Supply a nonempty resource ID or tag without controls")
        return value


class Paging(Input):
    page: int = Field(1, ge=1, title="Page")
    pageSize: int = Field(50, ge=1, le=100, title="Page Size")


class Search(Input):
    term: str | None = Field(None, title="Search Term")
    paging: Paging = Field(default_factory=Paging, title="Paging", description="One page per run. Increment page using the returned paging.pages value.")


class ContactID(Input):
    contact_id: str = Field(..., title="Contact ID", min_length=1)


class CampaignID(Input):
    campaign_id: str = Field(..., title="Campaign ID", min_length=1)


class ContactFields(Input):
    phoneNumber: str | None = Field(None, title="Phone Number")
    email: str | None = Field(None, title="Email", pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    firstName: str | None = Field(None, title="First Name")
    lastName: str | None = Field(None, title="Last Name")
    company: str | None = Field(None, title="Company")
    notes: str | None = Field(None, title="Notes")
    tags: list[str] | None = Field(None, title="Tags")
    doNotMessage: bool | None = Field(None, title="Do Not Message")
    doNotEmail: bool | None = Field(None, title="Do Not Email")


class MessageFields(Input):
    text: str | None = Field(None, title="Message Text", min_length=1)
    templateId: str | None = Field(None, title="Template ID", min_length=1)

    @model_validator(mode="after")
    def message_content(self):
        if not self.text and not self.templateId:
            raise ValueError("Provide message text or a template ID")
        return self


class Scheduled(Input):
    @field_validator("runAt", "scheduledAt", "eventDate", check_fields=False)
    @classmethod
    def valid_date(cls, value):
        if value is not None:
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (TypeError, ValueError):
                raise ValueError("Use an ISO 8601 date or date-time") from None
        return value


class TestConnection(Input):
    """Read the account name and phone number for this API key."""
    operation: Literal["test_connection"] = Field("test_connection", title="Test Connection", json_schema_extra={"ui:hidden": True})


class SearchContacts(Search):
    operation: Literal["search_contacts"] = Field("search_contacts", title="Search Contacts", json_schema_extra={"ui:hidden": True})
    tag: str | None = Field(None, title="Tag Filter")
    archived: bool | None = Field(None, title="Archived", description="Omitted returns non-archived contacts.")


class CreateContact(ContactFields):
    """Create a contact; existing phone numbers may be rejected by the provider."""
    operation: Literal["create_contact"] = Field("create_contact", title="Create Contact", json_schema_extra={"ui:hidden": True})
    phoneNumber: str = Field(..., title="Phone Number", min_length=1)


class GetContact(Input):
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})
    contact: str = Field(..., title="Contact ID, Phone or Email", min_length=1)


class UpdateContact(ContactID, ContactFields):
    """Update only supplied fields; omitted fields are preserved."""
    operation: Literal["update_contact"] = Field("update_contact", title="Update Contact", json_schema_extra={"ui:hidden": True})


class DeleteContact(ContactID):
    """Permanently delete the selected contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", title="Delete Contact", json_schema_extra={"ui:hidden": True})


class ArchiveContact(ContactID):
    """Archive the contact and stop message delivery without changing opt-out flags."""
    operation: Literal["archive_contact"] = Field("archive_contact", title="Archive Contact", json_schema_extra={"ui:hidden": True})


class UnarchiveContact(ContactID):
    """Unarchive the contact while retaining existing opt-out flags."""
    operation: Literal["unarchive_contact"] = Field("unarchive_contact", title="Unarchive Contact", json_schema_extra={"ui:hidden": True})


class SendMessage(ContactID, MessageFields, Scheduled):
    """Send or schedule a text or template message to one contact."""
    operation: Literal["send_message"] = Field("send_message", title="Send Message", json_schema_extra={"ui:hidden": True})
    runAt: str | None = Field(None, title="Send At", json_schema_extra={"format": "date-time"}, description="ISO 8601; omitted sends immediately. Offsetless times use the account timezone.")


class CreateBroadcast(MessageFields, Scheduled):
    """Send or schedule one message to multiple contacts."""
    operation: Literal["create_broadcast"] = Field("create_broadcast", title="Create Broadcast", json_schema_extra={"ui:hidden": True})
    contacts: list[str] = Field(..., min_length=1, title="Contact IDs")
    scheduledAt: str | None = Field(None, title="Scheduled At", json_schema_extra={"format": "date-time"}, description="ISO 8601; omitted sends immediately. Offsetless times use the account timezone.")


class SearchCampaigns(Search):
    operation: Literal["search_campaigns"] = Field("search_campaigns", title="Search Campaigns", json_schema_extra={"ui:hidden": True})


class GetCampaign(CampaignID):
    operation: Literal["get_campaign"] = Field("get_campaign", title="Get Campaign", json_schema_extra={"ui:hidden": True})


class AddContactToCampaign(ContactID, CampaignID, Scheduled):
    operation: Literal["add_contact_to_campaign"] = Field("add_contact_to_campaign", title="Add Contact To Campaign", json_schema_extra={"ui:hidden": True})
    eventDate: str | None = Field(None, title="Event Date", json_schema_extra={"format": "date-time"}, description="ISO 8601; required by the provider for event campaigns.")


class RemoveContactFromCampaign(ContactID, CampaignID):
    operation: Literal["remove_contact_from_campaign"] = Field("remove_contact_from_campaign", title="Remove Contact From Campaign", json_schema_extra={"ui:hidden": True})


class SearchTemplates(Search):
    operation: Literal["search_templates"] = Field("search_templates", title="Search Templates", json_schema_extra={"ui:hidden": True})
    contentType: Literal["MessageTemplate", "VoiceDrop", "Email"] | None = Field(None, title="Content Type")


class SearchKeywords(Search):
    operation: Literal["search_keywords"] = Field("search_keywords", title="Search Keywords", json_schema_extra={"ui:hidden": True})


class GetCustomFields(Input):
    operation: Literal["get_custom_fields"] = Field("get_custom_fields", title="Get Custom Fields", json_schema_extra={"ui:hidden": True})


class GetContactCustomFields(ContactID):
    operation: Literal["get_contact_custom_fields"] = Field("get_contact_custom_fields", title="Get Contact Custom Fields", json_schema_extra={"ui:hidden": True})


class UpdateContactCustomField(ContactID):
    """Set or clear one custom field with strict provider validation."""
    operation: Literal["update_contact_custom_field"] = Field("update_contact_custom_field", title="Update Contact Custom Field", json_schema_extra={"ui:hidden": True})
    custom_field_id: str = Field(..., title="Custom Field ID", min_length=1)
    value: str = Field("", title="Value", description="Empty string clears the field. Invalid typed values are rejected.")


class AddTagToContacts(Input):
    operation: Literal["add_tag_to_contacts"] = Field("add_tag_to_contacts", title="Add Tag To Contacts", json_schema_extra={"ui:hidden": True})
    tag: str = Field(..., title="Tag", min_length=1)
    contactIds: list[str] = Field(..., title="Contact IDs", min_length=1)


class RemoveTagFromContacts(Input):
    operation: Literal["remove_tag_from_contacts"] = Field("remove_tag_from_contacts", title="Remove Tag From Contacts", json_schema_extra={"ui:hidden": True})
    tag: str = Field(..., title="Tag", min_length=1)
    contactIds: list[str] = Field(..., title="Contact IDs", min_length=1)


class GetCredits(Input):
    operation: Literal["get_credits"] = Field("get_credits", title="Get Credits", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[TestConnection, SearchContacts, CreateContact, GetContact, UpdateContact, DeleteContact, ArchiveContact, UnarchiveContact, SendMessage, CreateBroadcast, SearchCampaigns, GetCampaign, AddContactToCampaign, RemoveContactFromCampaign, SearchTemplates, SearchKeywords, GetCustomFields, GetContactCustomFields, UpdateContactCustomField, AddTagToContacts, RemoveTagFromContacts, GetCredits], Field(discriminator="operation")]


class ProjectBroadcastConfig(NodeConfig[Operation, ProjectBroadcastAPIKey]):
    pass


ROUTES = {'test_connection': ('GET', '/auth/keytest'),
 'search_contacts': ('POST', '/contacts/search'),
 'create_contact': ('POST', '/contacts'),
 'get_contact': ('GET', '/contacts/{contact}'),
 'update_contact': ('PUT', '/contacts/{contact_id}'),
 'delete_contact': ('DELETE', '/contacts/{contact_id}'),
 'archive_contact': ('PUT', '/contacts/{contact_id}/archive'),
 'unarchive_contact': ('PUT', '/contacts/{contact_id}/unarchive'),
 'send_message': ('POST', '/contacts/{contact_id}/send'),
 'create_broadcast': ('POST', '/broadcasts'),
 'search_campaigns': ('POST', '/campaigns/search'),
 'get_campaign': ('GET', '/campaigns/{campaign_id}'),
 'add_contact_to_campaign': ('PUT', '/campaigns/{campaign_id}/contacts/{contact_id}/add'),
 'remove_contact_from_campaign': ('PUT', '/campaigns/{campaign_id}/contacts/{contact_id}/remove'),
 'search_templates': ('POST', '/templates/search'),
 'search_keywords': ('POST', '/keywords/search'),
 'get_custom_fields': ('GET', '/customFields'),
 'get_contact_custom_fields': ('GET', '/contacts/{contact_id}/customFields'),
 'update_contact_custom_field': ('PUT', '/contacts/{contact_id}/customFields/{custom_field_id}'),
 'add_tag_to_contacts': ('PUT', '/tags/{tag}/contacts/add'),
 'remove_tag_from_contacts': ('PUT', '/tags/{tag}/contacts/remove'),
 'get_credits': ('GET', '/user/credits')}


class ProjectBroadcastNode(WorkflowNode):
    integration_type = "automation-project-broadcast"
    connection_evidence = ConnectionEvidence(noun="Project Broadcast account", identity_operation="test_connection", identity_keys=("name", "phoneNumber"))

    @classmethod
    def get_config_model(cls):
        return ProjectBroadcastConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Project Broadcast API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, route = ROUTES[config.operation]
        body = config.model_dump(exclude_none=True, exclude={"operation"})
        for field in re.findall(r"{([^}]+)}", route):
            route = route.replace("{" + field + "}", quote(body.pop(field), safe=""))
        if config.operation == "update_contact_custom_field":
            body["requireValidCustomFields"] = True
        # These actions have no request body in the published contract.
        has_body = config.operation in {
            "search_contacts", "create_contact", "update_contact", "send_message", "create_broadcast",
            "search_campaigns", "add_contact_to_campaign", "search_templates", "search_keywords",
            "update_contact_custom_field", "add_tag_to_contacts", "remove_tag_from_contacts",
        }
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            try:
                response = await client.request(method, BASE + route,
                    headers={"x-api-key": key, "Accept": "application/json"},
                    **({"json": body} if has_body else {}))
            except httpx.HTTPError:
                # Never retry mutations: a transport failure can follow an accepted write.
                raise ValueError("Project Broadcast request did not complete; check its outcome before retrying a write") from None
        if not 200 <= response.status_code < 300:
            message = "Project Broadcast rejected the request"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("error"), str):
                    message = error["error"]
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": message.replace(key, "[redacted]")}
        if not response.content:
            if config.operation == "delete_contact":
                return {"status": "success", "operation": config.operation}
            raise ValueError("Project Broadcast returned an empty response")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Project Broadcast returned invalid JSON") from None
        if not isinstance(data, (dict, list)):
            raise ValueError("Project Broadcast returned an unexpected response")
        if isinstance(data, dict) and "error" in data:
            return {"status": "error", "error": str(data["error"]).replace(key, "[redacted]")}
        if config.operation == "test_connection" and (not isinstance(data, dict) or not isinstance(data.get("name"), str) or not isinstance(data.get("message"), str)):
            raise ValueError("Project Broadcast did not confirm the account identity")
        return {"status": "success", "operation": config.operation, "data": data}
