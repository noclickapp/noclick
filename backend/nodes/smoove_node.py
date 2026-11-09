"""Smoove REST v1 contacts, lists, leads and campaign reporting.

Each operation issues one request from the provider's published Swagger contract.
API keys use the Bearer header shown by https://rest.smoove.io/.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://rest.smoove.io"


class SmooveAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Smoove API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://rest.smoove.io/",
        "x-credential-instructions": "Create an API key in Smoove's API settings and paste it here without the Bearer prefix. Listing your lists verifies account access. The key needs AccountMembersRead for reads, AccountSubscriptions for contact updates, AccountAdmin for creating lists, and AccountCrm for CRM notes; provider role alternatives are documented per endpoint."})
    credential_type: Literal["smoove_api_key"] = Field("smoove_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without whitespace or the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("id", mode="before", check_fields=False)
    @classmethod
    def path_identifier(cls, value):
        if isinstance(value, str) and (
            value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("Use a resource identifier without dot segments or control characters")
        return value


class ListContacts(_Input):
    """Get active contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})
    fields: str = Field('id,externalid,email,cellphone,firstname,lastname,timestampSignup,lastChanged', description='Comma-separated contact fields to return', max_length=10000)
    page: int = Field(1, description='1-based page index (default: 1)', ge=1)
    itemsPerPage: int = Field(100, description='Number of records per page (default: 100, max: 100)', ge=1, le=100)
    sort: str = Field('-id', description='Sort fields (prefix `-` for descending), e.g. `-id`', max_length=10000)
    includeCustomFields: bool = Field(False, description='`true` to include contact custom fields')
    includeLinkedLists: bool = Field(False, description='`true` to include contact linked list ids')

class CreateContact(_Input):
    """Create or update a contact."""
    operation: Literal["create_contact"] = Field("create_contact", title="Create Contact", json_schema_extra={"ui:hidden": True})
    externalId: str | None = Field(None, max_length=10000)
    email: str = Field(..., max_length=10000, min_length=1)
    phone: str | None = Field(None, max_length=10000)
    cellPhone: str | None = Field(None, max_length=10000)
    mobile: str | None = Field(None, max_length=10000)
    firstName: str | None = Field(None, max_length=10000)
    lastName: str | None = Field(None, max_length=10000)
    dateOfBirth: str | None = Field(None, max_length=10000)
    address: str | None = Field(None, max_length=10000)
    city: str | None = Field(None, max_length=10000)
    country: str | None = Field(None, max_length=10000)
    company: str | None = Field(None, max_length=10000)
    position: str | None = Field(None, max_length=10000)
    canReceiveEmails: bool | None = Field(None)
    canReceiveSmsMessages: bool | None = Field(None)
    canReceiveWhatsappMessages: bool | None = Field(None)
    lists_ToSubscribe: list[int] | None = Field(None, description='Existing list IDs to subscribe this contact to. May trigger Smoove automations.')
    lists_ToUnsubscribe: list[int] | None = Field(None, description='Existing list IDs to remove this contact from.')
    customFields: dict[str, Any] | None = Field(None)
    options: dict[str, Any] | None = Field(None)
    campaignSource: str | None = Field(None, max_length=10000)
    updateIfExists: bool = Field(False, description='`true` to update an existing matching contact instead of failing on duplicate')
    restoreIfDeleted: bool = Field(False, description='`true` to restore the contact if it was deleted')
    restoreIfUnsubscribed: bool = Field(False, description='`true` to restore the contact if it was unsubscribed')
    overrideNullableValue: bool = Field(False, description='Controls whether null/empty values clear existing custom field values')

class GetContact(_Input):
    """Get a contact by identifier."""
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Contact identifier value (meaning depends on `by`)', max_length=10000, min_length=1)
    by: Literal['ContactId', 'Email', 'CellPhone', 'ExternalId'] = Field('ContactId', description='Identify by `ContactId` (default), `Email`, `Cellphone`, or `ExternalId`')
    fields: str | None = Field(None, description='Comma-separated contact fields to return', max_length=10000)
    includeCustomFields: bool = Field(False, description='`true` to include contact custom fields')
    includeLinkedLists: bool = Field(False, description='`true` to include contact linked list ids')

class UpdateContact(_Input):
    """Update a contact."""
    operation: Literal["update_contact"] = Field("update_contact", title="Update Contact", json_schema_extra={"ui:hidden": True})
    externalId: str | None = Field(None, max_length=10000)
    email: str | None = Field(None, max_length=10000)
    phone: str | None = Field(None, max_length=10000)
    cellPhone: str | None = Field(None, max_length=10000)
    mobile: str | None = Field(None, max_length=10000)
    firstName: str | None = Field(None, max_length=10000)
    lastName: str | None = Field(None, max_length=10000)
    dateOfBirth: str | None = Field(None, max_length=10000)
    address: str | None = Field(None, max_length=10000)
    city: str | None = Field(None, max_length=10000)
    country: str | None = Field(None, max_length=10000)
    company: str | None = Field(None, max_length=10000)
    position: str | None = Field(None, max_length=10000)
    canReceiveEmails: bool | None = Field(None)
    canReceiveSmsMessages: bool | None = Field(None)
    canReceiveWhatsappMessages: bool | None = Field(None)
    lists_ToSubscribe: list[int] | None = Field(None, description='Existing list IDs to subscribe this contact to. May trigger Smoove automations.')
    lists_ToUnsubscribe: list[int] | None = Field(None, description='Existing list IDs to remove this contact from.')
    customFields: dict[str, Any] | None = Field(None)
    options: dict[str, Any] | None = Field(None)
    campaignSource: str | None = Field(None, max_length=10000)
    id: str = Field(..., description='Contact identifier value (meaning depends on `by`)', max_length=10000, min_length=1)
    by: Literal['ContactId', 'Email', 'CellPhone', 'ExternalId'] = Field('ContactId', description='Identify by `ContactId` (default), `Email`, `Cellphone`, or `ExternalId`')
    restoreIfDeleted: bool = Field(False, description='`true` to restore the contact if it was deleted')
    restoreIfUnsubscribed: bool = Field(False, description='`true` to restore the contact if it was unsubscribed')
    overrideNullableValue: bool = Field(False, description='Controls whether null/empty values clear existing custom field values')

class ContactExists(_Input):
    """Check if a contact exists."""
    operation: Literal["contact_exists"] = Field("contact_exists", title="Contact Exists", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Contact identifier value (meaning depends on `by`)', max_length=10000, min_length=1)
    by: Literal['ContactId', 'Email', 'CellPhone', 'ExternalId'] = Field(..., description='Identify by `ContactId`, `Email`, `Cellphone`, or `ExternalId`')

class UnsubscribeContact(_Input):
    """Unsubscribe a contact."""
    operation: Literal["unsubscribe_contact"] = Field("unsubscribe_contact", title="Unsubscribe Contact", json_schema_extra={"ui:hidden": True})
    reason: str | None = Field(None, max_length=10000)
    id: str = Field(..., description='Contact identifier value (meaning depends on `by`)', max_length=10000, min_length=1)
    by: Literal['ContactId', 'Email', 'CellPhone', 'ExternalId'] = Field(..., description='Identify by `ContactId`, `Email`, `Cellphone`, or `ExternalId`')

class GetContactStatus(_Input):
    """Get a contact status by identifier."""
    operation: Literal["get_contact_status"] = Field("get_contact_status", title="Get Contact Status", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Contact identifier value (meaning depends on `by`)', max_length=10000, min_length=1)
    by: Literal['ContactId', 'Email', 'CellPhone', 'ExternalId'] = Field('ContactId', description='Identify by `ContactId` (default), `Email`, `Cellphone`, or `ExternalId`')

class ListUnsubscribedContacts(_Input):
    """Get unsubscribed contacts."""
    operation: Literal["list_unsubscribed_contacts"] = Field("list_unsubscribed_contacts", title="List Unsubscribed Contacts", json_schema_extra={"ui:hidden": True})
    fields: str = Field('id,externalid,email,cellphone,firstname,lastname,timestampSignup,lastChanged,timestampUnsubscribed,unsubscribeReasonType,unsubscribeReasonComment', description='Comma-separated contact fields to return', max_length=10000)
    page: int = Field(1, description='1-based page index (default: 1)', ge=1)
    itemsPerPage: int = Field(100, description='Number of records per page (default: 100, max: 100)', ge=1, le=100)
    sort: str = Field('-timestampUnsubscribed', description='Sort fields (prefix `-` for descending), e.g. `-timestampUnsubscribed`', max_length=10000)
    includeCustomFields: bool = Field(False, description='`true` to include contact custom fields')
    includeLinkedLists: bool = Field(False, description='`true` to include contact linked list ids')

class ListContactFields(_Input):
    """Get account contact fields (system and custom)."""
    operation: Literal["list_contact_fields"] = Field("list_contact_fields", title="List Contact Fields", json_schema_extra={"ui:hidden": True})

class ListLists(_Input):
    """Get all lists."""
    operation: Literal["list_lists"] = Field("list_lists", title="List Lists", json_schema_extra={"ui:hidden": True})
    fields: str = Field('id,name', description='Comma-separated fields to return (e.g. `id,name,publicName,description`)', max_length=10000)
    page: int = Field(1, description='1-based page index (default: 1)', ge=1)
    itemsPerPage: int = Field(100, description='Number of records per page (default: 100; higher max allowed when `includeContactsCount` is false)', ge=1, le=100)
    sort: str = Field('name', description='Sort fields (prefix `-` for descending), e.g. `name` or `-id`', max_length=10000)
    includeContactsCount: bool = Field(False, description='`true` to include member/contact count per list')

class CreateList(_Input):
    """Create a new list."""
    operation: Literal["create_list"] = Field("create_list", title="Create List", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., max_length=10000, min_length=1)
    publicName: str | None = Field(None, max_length=10000)
    description: str | None = Field(None, max_length=10000)
    publicDescription: str | None = Field(None, max_length=10000)
    permissions: dict[str, Any] | None = Field(None)

class GetList(_Input):
    """Get a list by id."""
    operation: Literal["get_list"] = Field("get_list", title="Get List", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='List id', ge=1)
    fields: str | None = Field(None, description='Comma-separated fields to return (e.g. `name,publicName,description`)', max_length=10000)

class ListListContacts(_Input):
    """Get contacts in a list."""
    operation: Literal["list_list_contacts"] = Field("list_list_contacts", title="List List Contacts", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='List id', ge=1)
    fields: str = Field('id,externalid,email,cellphone,firstname,lastname,timestampSignup', description='Comma-separated contact fields to return', max_length=10000)
    page: int = Field(1, description='1-based page index (default: 1)', ge=1)
    itemsPerPage: int = Field(100, description='Number of records per page (default: 100, max: 100)', ge=1, le=100)
    sort: str = Field('-id', description='Sort fields (prefix `-` for descending), e.g. `-id`', max_length=10000)
    includeCustomFields: bool = Field(False, description='`true` to include contact custom fields')
    includeLinkedLists: bool = Field(False, description='`true` to include contact linked list ids')
    includeListAssociationTime: bool = Field(False, description='`true` to include when the contact was associated with this list')

class ListLandingPages(_Input):
    """Get active landing pages."""
    operation: Literal["list_landing_pages"] = Field("list_landing_pages", title="List Landing Pages", json_schema_extra={"ui:hidden": True})
    type: Literal['ALL', 'Facebook', 'LandingPage', 'Mobile', 'Embed', 'Popup'] = Field('ALL', description='Page type filter: `All` (default), `Facebook`, `LandingPage`, `Mobile`, `Embed`, or `Popup`')

class GetLandingPage(_Input):
    """Get a landing page by id."""
    operation: Literal["get_landing_page"] = Field("get_landing_page", title="Get Landing Page", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='Landing page id', ge=1)

class ListLandingPageRecipients(_Input):
    """Get contacts who subscribed via a landing page."""
    operation: Literal["list_landing_page_recipients"] = Field("list_landing_page_recipients", title="List Landing Page Recipients", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='Landing page id', ge=1)
    fields: str = Field('id,externalid,email,cellphone,firstname,lastname,timestampSignup', description='Comma-separated contact fields to return (e.g. `id,externalid,email,cellphone,firstname`)', max_length=10000)
    page: int = Field(1, description='1-based page index (default: 1)', ge=1)
    itemsPerPage: int = Field(100, description='Number of records per page (default: 100, max: 100)', ge=1, le=100)
    includeCustomFields: bool = Field(False, description='`true` to include contact custom fields')
    includeLinkedLists: bool = Field(False, description='`true` to include contact linked list ids')

class ListCampaignTemplates(_Input):
    """Get custom email campaign templates."""
    operation: Literal["list_campaign_templates"] = Field("list_campaign_templates", title="List Campaign Templates", json_schema_extra={"ui:hidden": True})
    fields: str = Field('id,name', description='Comma-separated fields to return (`id`, `name`, `imageUrl`, `timeStamp`)', max_length=10000)

class GetCampaignStatistics(_Input):
    """Get an email campaign's aggregated report."""
    operation: Literal["get_campaign_statistics"] = Field("get_campaign_statistics", title="Get Campaign Statistics", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Campaign id (or external id when `by=ExternalId`)', max_length=10000, min_length=1)
    by: Literal['CampaignId', 'ExternalId'] = Field('CampaignId', description='Identify campaign by `CampaignId` (default) or `ExternalId`')

class ListCampaignRecipients(_Input):
    """Get email campaign recipients and their responses."""
    operation: Literal["list_campaign_recipients"] = Field("list_campaign_recipients", title="List Campaign Recipients", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Campaign id (or external id when `by=ExternalId`)', max_length=10000, min_length=1)
    by: Literal['CampaignId', 'ExternalId'] = Field('CampaignId', description='Identify campaign by `CampaignId` (default) or `ExternalId`')
    page: int = Field(1, description='1-based page index (default: 1)', ge=1)
    itemsPerPage: int = Field(100, description='Number of records per page (default: 100, max: 100)', ge=1, le=100)

class CreateCommunication(_Input):
    """Create a CRM communication log entry."""
    operation: Literal["create_communication"] = Field("create_communication", title="Create Communication", json_schema_extra={"ui:hidden": True})
    contact: str = Field(..., max_length=10000, min_length=1)
    communicator: str = Field(..., max_length=10000, min_length=1)
    initiator: Literal['You', 'Customer'] = Field(...)
    date: str = Field(..., description='Communication date in dd/mm/yyyy format.', max_length=10000, min_length=1)
    time: str = Field(..., description='Communication time in hh:mm format.', max_length=10000, min_length=1)
    type: Literal['Phone', 'Email', 'Meeting', 'Comment', 'Website', 'SMS', 'PostMail', 'Other'] = Field(...)
    content: str | None = Field(None, max_length=10000)
    by: Literal['ContactId', 'Email', 'CellPhone', 'ExternalId'] = Field('ContactId', description='How to resolve `Contact`: `ContactId` (default), `Email`, `CellPhone`, or `ExternalId`')


SmooveOperation = Annotated[Union[ListContacts, CreateContact, GetContact, UpdateContact, ContactExists, UnsubscribeContact, GetContactStatus, ListUnsubscribedContacts, ListContactFields, ListLists, CreateList, GetList, ListListContacts, ListLandingPages, GetLandingPage, ListLandingPageRecipients, ListCampaignTemplates, GetCampaignStatistics, ListCampaignRecipients, CreateCommunication], Field(discriminator="operation")]


class SmooveConfig(NodeConfig[SmooveOperation, SmooveAPIKeyCredential]):
    pass


ROUTES = {'list_contacts': ('GET',
                   '/v1/Contacts',
                   [],
                   ['fields', 'page', 'itemsPerPage', 'sort', 'includeCustomFields', 'includeLinkedLists'],
                   []),
 'create_contact': ('POST',
                    '/v1/Contacts',
                    [],
                    ['updateIfExists', 'restoreIfDeleted', 'restoreIfUnsubscribed', 'overrideNullableValue'],
                    ['externalId',
                     'email',
                     'phone',
                     'cellPhone',
                     'mobile',
                     'firstName',
                     'lastName',
                     'dateOfBirth',
                     'address',
                     'city',
                     'country',
                     'company',
                     'position',
                     'canReceiveEmails',
                     'canReceiveSmsMessages',
                     'canReceiveWhatsappMessages',
                     'lists_ToSubscribe',
                     'lists_ToUnsubscribe',
                     'customFields',
                     'options',
                     'campaignSource']),
 'get_contact': ('GET',
                 '/v1/Contacts/{id}',
                 ['id'],
                 ['by', 'fields', 'includeCustomFields', 'includeLinkedLists'],
                 []),
 'update_contact': ('PUT',
                    '/v1/Contacts/{id}',
                    ['id'],
                    ['by', 'restoreIfDeleted', 'restoreIfUnsubscribed', 'overrideNullableValue'],
                    ['externalId',
                     'email',
                     'phone',
                     'cellPhone',
                     'mobile',
                     'firstName',
                     'lastName',
                     'dateOfBirth',
                     'address',
                     'city',
                     'country',
                     'company',
                     'position',
                     'canReceiveEmails',
                     'canReceiveSmsMessages',
                     'canReceiveWhatsappMessages',
                     'lists_ToSubscribe',
                     'lists_ToUnsubscribe',
                     'customFields',
                     'options',
                     'campaignSource']),
 'contact_exists': ('GET', '/v1/Contacts/{id}/Exists', ['id'], ['by'], []),
 'unsubscribe_contact': ('POST', '/v1/Contacts/{id}/Unsubscribe', ['id'], ['by'], ['reason']),
 'get_contact_status': ('GET', '/v1/Contacts/status/{id}', ['id'], ['by'], []),
 'list_unsubscribed_contacts': ('GET',
                                '/v1/Contacts_Unsubscribers',
                                [],
                                ['fields',
                                 'page',
                                 'itemsPerPage',
                                 'sort',
                                 'includeCustomFields',
                                 'includeLinkedLists'],
                                []),
 'list_contact_fields': ('GET', '/v1/Account/ContactFields', [], [], []),
 'list_lists': ('GET',
                '/v1/Lists',
                [],
                ['fields', 'page', 'itemsPerPage', 'sort', 'includeContactsCount'],
                []),
 'create_list': ('POST',
                 '/v1/Lists',
                 [],
                 [],
                 ['name', 'publicName', 'description', 'publicDescription', 'permissions']),
 'get_list': ('GET', '/v1/Lists/{id}', ['id'], ['fields'], []),
 'list_list_contacts': ('GET',
                        '/v1/Lists/{id}/Contacts',
                        ['id'],
                        ['fields',
                         'page',
                         'itemsPerPage',
                         'sort',
                         'includeCustomFields',
                         'includeLinkedLists',
                         'includeListAssociationTime'],
                        []),
 'list_landing_pages': ('GET', '/v1/LandingPages', [], ['type'], []),
 'get_landing_page': ('GET', '/v1/LandingPages/{id}', ['id'], [], []),
 'list_landing_page_recipients': ('GET',
                                  '/v1/LandingPages/{id}/Recipients',
                                  ['id'],
                                  ['fields',
                                   'page',
                                   'itemsPerPage',
                                   'includeCustomFields',
                                   'includeLinkedLists'],
                                  []),
 'list_campaign_templates': ('GET', '/v1/Campaigns_Templates', [], ['fields'], []),
 'get_campaign_statistics': ('GET', '/v1/Campaigns/{id}/Statistics', ['id'], ['by'], []),
 'list_campaign_recipients': ('GET',
                              '/v1/Campaigns/{id}/Recipients',
                              ['id'],
                              ['by', 'page', 'itemsPerPage'],
                              []),
 'create_communication': ('POST',
                          '/v1/Communications',
                          [],
                          ['by'],
                          ['contact', 'communicator', 'initiator', 'date', 'time', 'type', 'content'])}


class SmooveNode(WorkflowNode):
    integration_type = "automation-smoove"
    connection_evidence = ConnectionEvidence(operation="list_lists", noun="Smoove lists")

    @classmethod
    def get_config_model(cls):
        return SmooveConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Smoove API key")
        method, path, path_fields, query_fields, body_fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, mode="json")
        for name in path_fields:
            path = path.replace("{" + name + "}", quote(str(values[name]), safe=""))
        params = {name: (str(values[name]).lower() if isinstance(values[name], bool) else values[name])
                  for name in query_fields if name in values}
        payload = {name: values[name] for name in body_fields if name in values} if body_fields else None
        headers = {"Authorization": "Bearer " + quote(credential.api_key, safe="~()*!.'-"), "Accept": "application/json"}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, params=params, headers=headers,
                                                **({"json": payload} if payload is not None else {}))
        except httpx.HTTPError:
            raise ValueError("Smoove could not be reached; retry the operation") from None
        if not 200 <= response.status_code < 300:
            # Preserve a provider's rejection for the shared connection verdict.
            try:
                error = response.json()
                if isinstance(error, dict):
                    error = error.get("message", error.get("Message", error.get("error", "Smoove rejected the request")))
                if not isinstance(error, str):
                    error = "Smoove rejected the request"
            except ValueError:
                error = "Smoove returned HTTP " + str(response.status_code)
            return {"status": "error", "http_status": response.status_code,
                    "error": error.replace(credential.api_key, "[redacted]")[:2000]}
        if len(response.content) > 5_000_000:
            raise ValueError("Smoove response exceeded the size limit")
        if response.headers.get("content-type", "").split(";", 1)[0].lower() not in {"application/json", "text/json"}:
            raise ValueError("Smoove did not return JSON")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Smoove returned invalid JSON") from None
        if isinstance(data, dict) and ("error" in data or "errors" in data):
            raise ValueError("Smoove returned an error response")
        output = {"status": "success", "operation": config.operation, "data": data}
        if config.operation.startswith("list_"):
            # Swagger documents a single row for several collection endpoints.
            # Accept both that published example and the API's array form.
            if not isinstance(data, (list, dict)):
                raise ValueError("Smoove returned an invalid collection")
            items = data if isinstance(data, list) else [data]
            if any(not isinstance(item, dict) or not item for item in items):
                raise ValueError("Smoove returned invalid collection rows")
            output["items"] = items
            if "page" in values:
                output["page"] = values["page"]
                # A full page only suggests another page; it does not prove one.
                output["next_page_hint"] = values["page"] + 1 if len(items) >= values["itemsPerPage"] else None
        elif config.operation == "contact_exists":
            if not isinstance(data, bool):
                raise ValueError("Smoove did not return an existence flag")
        elif config.operation == "unsubscribe_contact":
            if not isinstance(data, str):
                raise ValueError("Smoove did not confirm the unsubscribe")
        elif not isinstance(data, dict):
            raise ValueError("Smoove returned an invalid record")
        return output
