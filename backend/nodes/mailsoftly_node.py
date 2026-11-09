"""Mailsoftly v3: account, audience management and campaign reporting.

Contract: https://app.mailsoftly.com/developers/openapi.json (v3).
Each operation makes exactly one provider request; paginated reads return one page.
"""
from typing import Annotated, Literal, Optional, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class MailsoftlyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Mailsoftly API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.mailsoftly.com",
        "x-credential-instructions": "In Mailsoftly, open Settings → API Keys and create a key with permissions for the operations you need. Copy the key when it is shown and paste it here. NoClick sends the raw key in the Authorization header. Connection verification reads your account profile (account:read). New keys expire one year after creation."})
    credential_type: Literal["mailsoftly_api_key"] = Field("mailsoftly_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the raw Mailsoftly API key")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetAccountConfig(_Operation):
    """Get account info."""
    operation: Literal['get_account'] = Field('get_account', json_schema_extra={"ui:hidden": True})

class GetContactsConfig(_Operation):
    """List all contacts."""
    operation: Literal['get_contacts'] = Field('get_contacts', json_schema_extra={"ui:hidden": True})
    page: int = Field(1 ,ge=1, description='Page number. Passing page or per_page switches the response to the paginated envelope {contacts, page, per_page, total, has_more}.')
    per_page: int = Field(50 ,le=500, ge=1, description='Rows per page, up to 500.')
    order: Literal['oldest', 'newest', 'recently_updated'] = Field('oldest' ,description='Row order. oldest (the default) is by id ascending; newest is by created_at descending; recently_updated is by updated_at descending. Ties break on id. Any other value returns 422.')
    created_since: Optional[str] = Field(None ,description='ISO8601 date or time. Returns only contacts created at or after it. An unparseable value returns 422.')
    updated_since: Optional[str] = Field(None ,description='ISO8601 date or time. Returns only contacts changed at or after it. An unparseable value returns 422.')

class GetContactConfig(_Operation):
    """Get a single contact."""
    operation: Literal['get_contact'] = Field('get_contact', json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(... ,description='The ID of the contact to retrieve')
    type: Optional[Literal['detailed']] = Field(None ,description='Pass "detailed" for full contact data')

class CreateContactConfig(_Operation):
    """Create a new contact."""
    operation: Literal['create_contact'] = Field('create_contact', json_schema_extra={"ui:hidden": True})
    first_name: Optional[str] = Field(None)
    last_name: Optional[str] = Field(None)
    email: str = Field(...)
    job_title: Optional[str] = Field(None)
    mobile_phone: Optional[str] = Field(None)
    work_phone: Optional[str] = Field(None)
    website: Optional[str] = Field(None)
    address: Optional[str] = Field(None)
    address_line_1: Optional[str] = Field(None)
    address_line_2: Optional[str] = Field(None)
    note: Optional[str] = Field(None)
    date_of_birth: Optional[str] = Field(None ,description="YYYY-MM-DD, or --MM-DD for a birthday without its year. A value that cannot be read is not saved and is reported in the response's warnings.")
    gender: Optional[str] = Field(None)
    country: Optional[str] = Field(None)
    city: Optional[str] = Field(None)
    state: Optional[str] = Field(None)
    zip_code: Optional[str] = Field(None)
    email_sending_status: Optional[Literal['nonesubscribed', 'subscribed', 'unsubscribed', 'bounced', 'complaint']] = Field(None)
    industry: Optional[str] = Field(None)
    company: Optional[str] = Field(None)
    source: Optional[str] = Field(None)
    opt_in_date: Optional[str] = Field(None)

class UpdateContactConfig(_Operation):
    """Update an existing contact."""
    operation: Literal['update_contact'] = Field('update_contact', json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(... ,description='ID of the contact to update')
    first_name: Optional[str] = Field(None)
    last_name: Optional[str] = Field(None)
    email: Optional[str] = Field(None)
    job_title: Optional[str] = Field(None)
    company: Optional[str] = Field(None)
    country: Optional[str] = Field(None)
    city: Optional[str] = Field(None)

class CreateOrUpdateContactConfig(_Operation):
    """Create or update a contact."""
    operation: Literal['create_or_update_contact'] = Field('create_or_update_contact', json_schema_extra={"ui:hidden": True})
    contact_id: Optional[int] = Field(None ,description='ID of an existing contact to update. Omit it to match by email, or to create.')
    first_name: Optional[str] = Field(None)
    last_name: Optional[str] = Field(None)
    email: str = Field(...)
    job_title: Optional[str] = Field(None)
    company: Optional[str] = Field(None)
    country: Optional[str] = Field(None)
    city: Optional[str] = Field(None)
    source: Optional[str] = Field(None)

class SearchContactsConfig(_Operation):
    """Search contacts."""
    operation: Literal['search_contacts'] = Field('search_contacts', json_schema_extra={"ui:hidden": True})
    email: Optional[str] = Field(None ,description='Exact email address to search for')
    first_name: Optional[str] = Field(None ,description='Exact first name to search for')
    last_name: Optional[str] = Field(None ,description='Exact last name to search for')
    page: int = Field(1 ,ge=1, description='Page number. Passing page or per_page switches the response to the paginated envelope {contacts, page, per_page, total, has_more}.')
    per_page: int = Field(50 ,le=500, ge=1, description='Rows per page, up to 500.')

class GetContactListsConfig(_Operation):
    """List all contact lists."""
    operation: Literal['get_contact_lists'] = Field('get_contact_lists', json_schema_extra={"ui:hidden": True})

class GetContactListConfig(_Operation):
    """Get a single contact list."""
    operation: Literal['get_contact_list'] = Field('get_contact_list', json_schema_extra={"ui:hidden": True})
    contact_list_id: int = Field(... ,description='ID of the contact list')

class GetContactListContactsConfig(_Operation):
    """List contacts in a contact list."""
    operation: Literal['get_contact_list_contacts'] = Field('get_contact_list_contacts', json_schema_extra={"ui:hidden": True})
    contact_list_id: int = Field(... ,description='ID of the contact list')
    page: int = Field(1 ,ge=1, description='Page number. Passing page or per_page switches the response to the paginated envelope {contacts, page, per_page, total, has_more}.')
    per_page: int = Field(50 ,le=500, ge=1, description='Rows per page, up to 500.')
    order: Literal['oldest', 'newest', 'recently_updated'] = Field('oldest' ,description="Row order. oldest (the default) is by id ascending; newest is by added_at descending, the most recent additions to this list first; recently_updated is by the contact's updated_at descending. Ties break on id. Any other value returns 422.")
    created_since: Optional[str] = Field(None ,description='ISO8601 date or time. Returns only contacts created at or after it. An unparseable value returns 422.')
    updated_since: Optional[str] = Field(None ,description='ISO8601 date or time. Returns only contacts changed at or after it. An unparseable value returns 422.')

class CreateContactListConfig(_Operation):
    """Create a new contact list."""
    operation: Literal['create_contact_list'] = Field('create_contact_list', json_schema_extra={"ui:hidden": True})
    name: str = Field(... ,description='Name of the contact list')

class AddContactToContactListConfig(_Operation):
    """Add a single contact to a list."""
    operation: Literal['add_contact_to_contact_list'] = Field('add_contact_to_contact_list', json_schema_extra={"ui:hidden": True})
    contact_list_id: int = Field(... ,description='ID of the contact list')
    contact_id: int = Field(... ,description='ID of the contact to add')

class GetTagsConfig(_Operation):
    """List all tags."""
    operation: Literal['get_tags'] = Field('get_tags', json_schema_extra={"ui:hidden": True})

class AssignTagToContactConfig(_Operation):
    """Assign a tag to a contact."""
    operation: Literal['assign_tag_to_contact'] = Field('assign_tag_to_contact', json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(... ,description='ID of the contact')
    tag_id: Optional[int] = Field(None ,description='ID of an existing tag (use this OR tag_name)')
    tag_name: Optional[str] = Field(None ,description='Name for the tag. It will be found or created')
    tag_color: Optional[str] = Field(None ,description='Color in hex (#FF0000) or RGB format')

    @model_validator(mode="after")
    def tag_selector(self):
        if (self.tag_id is None) == (self.tag_name is None):
            raise ValueError("Provide either tag_id or tag_name")
        return self

class GetCustomFieldsConfig(_Operation):
    """List all custom fields."""
    operation: Literal['get_custom_fields'] = Field('get_custom_fields', json_schema_extra={"ui:hidden": True})

class AddCustomFieldToContactConfig(_Operation):
    """Add a custom field to a contact."""
    operation: Literal['add_custom_field_to_contact'] = Field('add_custom_field_to_contact', json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(... ,description='ID of the contact')
    custom_field_name: str = Field(... ,description='Name of the custom field')
    custom_field_value: str = Field(... ,description='Value to set')

class CreateTagConfig(_Operation):
    """Create a tag."""
    operation: Literal['create_tag'] = Field('create_tag', json_schema_extra={"ui:hidden": True})
    name: str = Field(...)
    color: Optional[str] = Field(None)

class ListCampaignsConfig(_Operation):
    """List campaigns."""
    operation: Literal['list_campaigns'] = Field('list_campaigns', json_schema_extra={"ui:hidden": True})
    page: int = Field(1 ,ge=1)
    per_page: int = Field(50 ,le=100, ge=1)
    status: Optional[Literal['draft', 'review', 'sending', 'sent']] = Field(None)
    q: Optional[str] = Field(None ,description='Search in subject and name')

class GetCampaignStatsConfig(_Operation):
    """Get campaign performance."""
    operation: Literal['get_campaign_stats'] = Field('get_campaign_stats', json_schema_extra={"ui:hidden": True})
    id: int = Field(... ,description='Campaign id, from list_campaigns.')

class AddGlobalEmailUnsubscriberConfig(_Operation):
    """Globally unsubscribe an email."""
    operation: Literal['add_global_email_unsubscriber'] = Field('add_global_email_unsubscriber', json_schema_extra={"ui:hidden": True})
    email: str = Field(... ,description='Email to unsubscribe (required)')
    phone: Optional[str] = Field(None)
    first_name: Optional[str] = Field(None)
    last_name: Optional[str] = Field(None)

class RemoveGlobalEmailUnsubscriberConfig(_Operation):
    """Resubscribe an email."""
    operation: Literal['remove_global_email_unsubscriber'] = Field('remove_global_email_unsubscriber', json_schema_extra={"ui:hidden": True})
    email: str = Field(... ,description='Email to resubscribe (required)')
    first_name: Optional[str] = Field(None)
    last_name: Optional[str] = Field(None)
    phone: Optional[str] = Field(None)

class DeleteContactConfig(_Operation):
    """Delete a contact."""
    operation: Literal['delete_contact'] = Field('delete_contact', json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(...)

class UpdateContactListConfig(_Operation):
    """Rename a contact list."""
    operation: Literal['update_contact_list'] = Field('update_contact_list', json_schema_extra={"ui:hidden": True})
    contact_list_id: int = Field(...)
    name: str = Field(...)

Operation = Annotated[Union[GetAccountConfig, GetContactsConfig, GetContactConfig, CreateContactConfig, UpdateContactConfig, CreateOrUpdateContactConfig, SearchContactsConfig, GetContactListsConfig, GetContactListConfig, GetContactListContactsConfig, CreateContactListConfig, AddContactToContactListConfig, GetTagsConfig, AssignTagToContactConfig, GetCustomFieldsConfig, AddCustomFieldToContactConfig, CreateTagConfig, ListCampaignsConfig, GetCampaignStatsConfig, AddGlobalEmailUnsubscriberConfig, RemoveGlobalEmailUnsubscriberConfig, DeleteContactConfig, UpdateContactListConfig], Field(discriminator="operation")]

class MailsoftlyNodeConfig(NodeConfig[Operation, MailsoftlyAPIKeyCredential]):
    pass

ROUTES = {'get_account': ('GET', '/api/v3/get_account'), 'get_contacts': ('GET', '/api/v3/get_contacts'), 'get_contact': ('GET', '/api/v3/get_contact'), 'create_contact': ('POST', '/api/v3/create_contact'), 'update_contact': ('POST', '/api/v3/update_contact'), 'create_or_update_contact': ('POST', '/api/v3/create_or_update_contact'), 'search_contacts': ('GET', '/api/v3/search_contacts'), 'get_contact_lists': ('GET', '/api/v3/get_contact_lists'), 'get_contact_list': ('GET', '/api/v3/get_contact_list'), 'get_contact_list_contacts': ('GET', '/api/v3/get_contact_list_contacts'), 'create_contact_list': ('POST', '/api/v3/create_contact_list'), 'add_contact_to_contact_list': ('POST', '/api/v3/add_contact_to_contact_list'), 'get_tags': ('GET', '/api/v3/get_tags'), 'assign_tag_to_contact': ('POST', '/api/v3/assign_tag_to_contact'), 'get_custom_fields': ('GET', '/api/v3/get_custom_fields'), 'add_custom_field_to_contact': ('POST', '/api/v3/add_custom_field_to_contact'), 'create_tag': ('POST', '/api/v3/create_tag'), 'list_campaigns': ('GET', '/api/v3/list_campaigns'), 'get_campaign_stats': ('GET', '/api/v3/get_campaign_stats'), 'add_global_email_unsubscriber': ('POST', '/api/v3/add_global_email_unsubscriber'), 'remove_global_email_unsubscriber': ('POST', '/api/v3/remove_global_email_unsubscriber'), 'delete_contact': ('POST', '/api/v3/delete_contact'), 'update_contact_list': ('POST', '/api/v3/update_contact_list')}


class MailsoftlyNode(WorkflowNode):
    integration_type = "automation-mailsoftly"
    connection_evidence = ConnectionEvidence(noun="Mailsoftly account", identity_operation="get_account", operation="get_account", label_keys=("name", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return MailsoftlyNodeConfig

    async def execute(self, inputs):
        if self.config.credentials is None:
            raise ValueError("Connect a Mailsoftly API key")
        op = self.config.config
        method, path = ROUTES[op.operation]
        payload = op.model_dump(exclude={"operation"}, exclude_none=True)
        key = self.config.credentials.api_key
        async with guarded_async_client(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, "https://app.mailsoftly.com" + path,
                headers={"Authorization": key, "Accept": "application/json"},
                **({"params": payload} if method == "GET" else {"json": payload}))
        try:
            result = response.json()
        except ValueError:
            raise ValueError(f"Mailsoftly returned an unreadable response (HTTP {response.status_code})") from None
        if response.is_error or response.is_redirect or (isinstance(result, dict) and (result.get("status") == "error" or result.get("error"))):
            message = result.get("error", "Mailsoftly request failed") if isinstance(result, dict) else "Mailsoftly request failed"
            raise ValueError(str(message).replace(key, "[redacted]"))
        if not isinstance(result, (dict, list)):
            raise ValueError("Mailsoftly returned an unexpected response")
        await self.emit(result)
        return result
