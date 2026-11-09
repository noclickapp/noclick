"""LeadSimple REST operations using a manually supplied bearer access token.

Each operation maps to one published REST endpoint. Responses retain provider
JSON, and list operations fetch one explicit page without following links.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote, urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.leadsimple.com/rest"


class LeadSimpleTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="LeadSimple API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.leadsimple.com/",
            "x-credential-instructions": "Paste your LeadSimple REST API access token. NoClick sends it as a bearer token to api.leadsimple.com. The account read verifies the account this token can access.",
        },
    )
    credential_type: Literal["leadsimple_api_token"] = Field("leadsimple_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the token alone, without the Bearer prefix")
        return value


class LeadSimpleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def page_bound(self):
        # LeadSimple caps custom-field pages at 100 instead of 200.
        if getattr(self, "include_custom_fields", False) and getattr(self, "per_page", 25) > 100:
            raise ValueError("Use per_page <= 100 when including custom fields")
        return self


class LeadSimpleGetAccountConfig(LeadSimpleInput):
    """Info about the current account."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})

class LeadSimpleGetUserConfig(LeadSimpleInput):
    """Info about the current user."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})

class LeadSimpleListContactsConfig(LeadSimpleInput):
    """Returns a list of contacts on the account."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    per_page: int = Field(25, ge=1, le=200, description='This is limited to the `[1, 200]` range except where noted otherwise.')
    search: str | None = Field(None, max_length=20000, description='Filters contacts by name, email, or phone number')
    updated_since: int | None = Field(None, ge=0, description='Filter contacts updated since a certain unix timestamp')
    include_custom_fields: bool | None = Field(None, description='Whether we should or not include custom fields in the returned deals. If true, the `per_page` size is capped to 100. Keep in mind requesting custom fields means this request will take longer.')

class LeadSimpleCreateContactConfig(LeadSimpleInput):
    """Create a contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    first_name: str | None = Field(None, max_length=20000, description='The first name of the contact')
    last_name: str | None = Field(None, max_length=20000, description='The last name of the contact')
    company_name: str | None = Field(None, max_length=20000, description='The company name of the contact')
    email_addresses: list[str] | None = Field(None, max_length=200, description="The contact's email addresses", json_schema_extra={"ui:widget": "list"})
    tags: list[str] | None = Field(None, max_length=200, description='Tags to assign to contact', json_schema_extra={"ui:widget": "list"})
    mailing_address: str | None = Field(None, max_length=20000, description='The mailing address line 1')
    mailing_city: str | None = Field(None, max_length=20000, description='The mailing address city')
    mailing_state: str | None = Field(None, max_length=20000, description='The mailing address state')
    mailing_zip_code: str | None = Field(None, max_length=20000, description='The mailing address zip code')

class LeadSimpleUpdateContactConfig(LeadSimpleInput):
    """Updates a contact."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    first_name: str | None = Field(None, max_length=20000, description='The first name of the contact')
    last_name: str | None = Field(None, max_length=20000, description='The last name of the contact')
    company_name: str | None = Field(None, max_length=20000, description='The company name of the contact')
    email_addresses: list[str] | None = Field(None, max_length=200, description="The contact's email addresses", json_schema_extra={"ui:widget": "list"})
    tags: list[str] | None = Field(None, max_length=200, description='Tags to assign to contact', json_schema_extra={"ui:widget": "list"})
    mailing_address: str | None = Field(None, max_length=20000, description='The mailing address line 1')
    mailing_city: str | None = Field(None, max_length=20000, description='The mailing address city')
    mailing_state: str | None = Field(None, max_length=20000, description='The mailing address state')
    mailing_zip_code: str | None = Field(None, max_length=20000, description='The mailing address zip code')
    secondary_name: str | None = Field(None, max_length=20000, description='The secondary or company name of the contact')

class LeadSimpleListDealsConfig(LeadSimpleInput):
    """Returns a list of deals on the account filterable by pipeline, name, email, or phone number."""
    operation: Literal["list_deals"] = Field("list_deals", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    per_page: int = Field(25, ge=1, le=200, description='This is limited to the `[1, 200]` range except where noted otherwise.')
    pipeline_id: str | None = Field(None, max_length=20000, description='Pipeline to filter deals by')
    search: str | None = Field(None, max_length=20000, description="Filters deals by name, email, or phone number. We'll include custom fields if this is present in the request.")
    include_custom_fields: bool | None = Field(None, description='Whether we should or not include custom fields in the returned deals. If true, the `per_page` size is capped to 100. Keep in mind requesting custom fields means this request will take longer.')
    updated_since: int | None = Field(None, ge=0, description='Filter deals updated since a certain UNIX timestamp')

class LeadSimpleGetDealConfig(LeadSimpleInput):
    """Returns an individual deal."""
    operation: Literal["get_deal"] = Field("get_deal", json_schema_extra={"ui:hidden": True})
    deal_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    include_custom_fields: bool | None = Field(None, description='Whether we should or not include custom fields in the returned process.')

class LeadSimpleCreateDealConfig(LeadSimpleInput):
    """Create a deal."""
    operation: Literal["create_deal"] = Field("create_deal", json_schema_extra={"ui:hidden": True})
    deal_pipeline_id: str = Field(..., max_length=20000, description='Pipeline to create the deal in')
    deal_name: str | None = Field(None, max_length=20000, description='The name of the new deal')
    deal_stage_id: str | None = Field(None, max_length=20000, description='Stage to create the deal in')
    deal_assignee_id: str | None = Field(None, max_length=20000, description='User to assign the deal to')
    deal_source_id_or_name: str | None = Field(None, max_length=20000, description='Source to assign the deal to. Exact name or UID.')
    deal_comments: str | None = Field(None, max_length=20000, description='Comments related to the deal')
    deal_value: str | None = Field(None, max_length=20000, description='Value of the deal')
    deal_cost: str | None = Field(None, max_length=20000, description='Cost of the deal')
    deal_tags: list[str] | None = Field(None, max_length=200, description='Tags to assign to deal', json_schema_extra={"ui:widget": "list"})
    contact_full_name: str | None = Field(None, max_length=20000, description="The contact's full name (automatically parsed into first_name, last_name, & secondary name)")
    contact_email_addresses: list[str] | None = Field(None, max_length=200, description="The contact's email addresses", json_schema_extra={"ui:widget": "list"})
    deal_accept_duplicates: bool | None = Field(None, description='Allow creating duplicate deals based on email or phone')

class LeadSimpleUpdateDealConfig(LeadSimpleInput):
    """Updates a deal."""
    operation: Literal["update_deal"] = Field("update_deal", json_schema_extra={"ui:hidden": True})
    deal_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    pipeline_id: str = Field(..., max_length=20000, description='Pipeline to update the deal in')
    name: str | None = Field(None, max_length=20000, description='The name of the new deal')
    stage_id: str | None = Field(None, max_length=20000, description='Stage to move the deal into. If empty, the deal will be kept in the same stage.')
    assignee_id: str | None = Field(None, max_length=20000, description='User to assign the deal to')
    comments: str | None = Field(None, max_length=20000, description='Comments related to the deal')
    value: str | None = Field(None, max_length=20000, description='Value of the deal')
    cost: str | None = Field(None, max_length=20000, description='Cost of the deal')
    tags: list[str] | None = Field(None, max_length=200, description='Tags to assign to deal', json_schema_extra={"ui:widget": "list"})
    remove_tags: bool | None = Field(None, description="Whether you want to add or remove the tags you're passing")
    contact_ids: list[str] | None = Field(None, max_length=200, description='The IDs of the contacts related to this deal', json_schema_extra={"ui:widget": "list"})
    property_ids: list[str] | None = Field(None, max_length=200, description='The IDs of the properties related to this deal', json_schema_extra={"ui:widget": "list"})
    closed_at: str | None = Field(None, max_length=20000, description='When the deal was closed at')

class LeadSimpleListProcessesConfig(LeadSimpleInput):
    """Returns a list of processes on the account filterable by process type."""
    operation: Literal["list_processes"] = Field("list_processes", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    per_page: int = Field(25, ge=1, le=200, description='This is limited to the `[1, 200]` range except where noted otherwise.')
    process_type_id: str | None = Field(None, max_length=20000, description='Process type to filter processes by')
    search: str | None = Field(None, max_length=20000, description="Filters processes by name, email, or phone number.  We'll include custom fields if this is present in the request.")
    include_custom_fields: bool | None = Field(None, description='Whether we should or not include custom fields in the returned processes. If true, the `per_page` size is capped to 100. Keep in mind requesting custom fields means this request will take longer.')
    include_property_groups: bool | None = Field(None, description='Whether or not we should include property groups in the returned properties. Keep in mind requesting property groups could mean this request will take longer.')
    updated_since: int | None = Field(None, ge=0, description='Filter processes updated since a certain unix timestamp')

class LeadSimpleGetProcessConfig(LeadSimpleInput):
    """Returns an individual process."""
    operation: Literal["get_process"] = Field("get_process", json_schema_extra={"ui:hidden": True})
    process_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    include_custom_fields: bool | None = Field(None, description='Whether we should or not include custom fields in the returned process.')
    include_property_groups: bool | None = Field(None, description='Whether or not we should include property groups in the returned properties. Keep in mind requesting property groups could mean this request will take longer.')

class LeadSimpleCreateProcessConfig(LeadSimpleInput):
    """Create a process."""
    operation: Literal["create_process"] = Field("create_process", json_schema_extra={"ui:hidden": True})
    process_process_type_id: str = Field(..., max_length=20000, description='Pipeline to create the process in')
    process_stage_id: str = Field(..., max_length=20000, description='Stage to create the process in')
    process_name: str | None = Field(None, max_length=20000, description='The name of the new process')
    process_comments: str | None = Field(None, max_length=20000, description='Comments related to the process')
    process_due_at: str | None = Field(None, max_length=20000, description='When the process is due')
    process_user_id: str | None = Field(None, max_length=20000, description='User to assign the process to')
    process_tags: list[str] | None = Field(None, max_length=200, description='Tags to assign to process', json_schema_extra={"ui:widget": "list"})
    property_ids: list[str] | None = Field(None, max_length=200, description='The IDs of the properties related to this process', json_schema_extra={"ui:widget": "list"})
    unit_ids: list[str] | None = Field(None, max_length=200, description='The IDs of the units on the properties to associate', json_schema_extra={"ui:widget": "list"})

class LeadSimpleUpdateProcessConfig(LeadSimpleInput):
    """Updates a process."""
    operation: Literal["update_process"] = Field("update_process", json_schema_extra={"ui:hidden": True})
    process_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    name: str | None = Field(None, max_length=20000, description='The name of the new process')
    comments: str | None = Field(None, max_length=20000, description='Comments related to the process')
    due_at: str | None = Field(None, max_length=20000, description='When the process is due')
    stage_id: str | None = Field(None, max_length=20000, description='Stage to move the process into. If empty, the process will be kept in the same stage.')
    user_id: str | None = Field(None, max_length=20000, description='User to assign the process to')
    tags: list[str] | None = Field(None, max_length=200, description='Tags to assign to process', json_schema_extra={"ui:widget": "list"})
    remove_tags: bool | None = Field(None, description="Whether you want to add or remove the tags you're passing")
    closed_at: str | None = Field(None, max_length=20000, description='When the process is closed')

class LeadSimpleCreateNoteConfig(LeadSimpleInput):
    """Creates a note for a parent process or deal."""
    operation: Literal["create_note"] = Field("create_note", json_schema_extra={"ui:hidden": True})
    created_at: str | None = Field(None, max_length=20000, description="When the note was created at. If empty, we'll assume it was created at the time of the request.")
    description: str = Field(..., max_length=20000, description='Note to be added to the deal')
    direction: Literal['inbound', 'outbound'] | None = Field(None, description='Whether this note refers to an inbound/outbound email/call/text')
    kind: Literal['email', 'call', 'text'] | None = Field(None, description='Kind of note')
    parent_id: str = Field(..., max_length=20000, description='Deal or Process ID to assign the note activity to')
    parent_type: Literal['Deal', 'Process'] = Field(..., description='Whether this note belongs to a Process or a Deal')
    user_id: str | None = Field(None, max_length=20000, description='User to assign the note activity to')

class LeadSimpleListPipelinesConfig(LeadSimpleInput):
    """Returns a list of pipelines on the account."""
    operation: Literal["list_pipelines"] = Field("list_pipelines", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    per_page: int = Field(25, ge=1, le=200, description='This is limited to the `[1, 200]` range except where noted otherwise.')
    account_id: int | None = Field(None, ge=0, description='Account to fetch pipelines for')

class LeadSimpleGetPipelineConfig(LeadSimpleInput):
    """Returns an individual pipeline."""
    operation: Literal["get_pipeline"] = Field("get_pipeline", json_schema_extra={"ui:hidden": True})
    pipeline_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

class LeadSimpleListPipelineStagesConfig(LeadSimpleInput):
    """List workflow stages under a pipeline."""
    operation: Literal["list_pipeline_stages"] = Field("list_pipeline_stages", json_schema_extra={"ui:hidden": True})
    pipeline_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    page: int = Field(1, ge=1)
    per_page: int = Field(25, ge=1, le=200, description='This is limited to the `[1, 200]` range except where noted otherwise.')

class LeadSimpleListPipelineSourcesConfig(LeadSimpleInput):
    """List sources under a pipeline."""
    operation: Literal["list_pipeline_sources"] = Field("list_pipeline_sources", json_schema_extra={"ui:hidden": True})
    pipeline_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    page: int = Field(1, ge=1)
    per_page: int = Field(25, ge=1, le=200, description='This is limited to the `[1, 200]` range except where noted otherwise.')

class LeadSimpleListProcessTypesConfig(LeadSimpleInput):
    """Returns a list of process type on the account."""
    operation: Literal["list_process_types"] = Field("list_process_types", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    per_page: int = Field(25, ge=1, le=200, description='This is limited to the `[1, 200]` range except where noted otherwise.')

class LeadSimpleListProcessTypeStagesConfig(LeadSimpleInput):
    """List workflow stages under a process type."""
    operation: Literal["list_process_type_stages"] = Field("list_process_type_stages", json_schema_extra={"ui:hidden": True})
    process_type_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    page: int = Field(1, ge=1)
    per_page: int = Field(25, ge=1, le=200, description='This is limited to the `[1, 200]` range except where noted otherwise.')

class LeadSimpleListUsersConfig(LeadSimpleInput):
    """Returns a list of users on the account."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    per_page: int = Field(25, ge=1, le=200, description='This is limited to the `[1, 200]` range except where noted otherwise.')
    search: str | None = Field(None, max_length=20000, description='Naively filter users by email or name')

class LeadSimpleListPropertiesConfig(LeadSimpleInput):
    """Returns a list of properties on the account."""
    operation: Literal["list_properties"] = Field("list_properties", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    per_page: int = Field(25, ge=1, le=200, description='This is limited to the `[1, 200]` range except where noted otherwise.')
    search: str | None = Field(None, max_length=20000, description='Filters properties by name, address line 1, or address city')
    updated_since: int | None = Field(None, ge=0, description='Filter properties updated since a certain unix timestamp')
    include_custom_fields: bool | None = Field(None, description='Whether or not we should include custom fields in the returned properties. If true, the `per_page` size is capped to 100. Keep in mind requesting custom fields means this request will take longer.')
    include_property_groups: bool | None = Field(None, description='Whether or not we should include property groups in the returned properties. Keep in mind requesting property groups could mean this request will take longer.')

class LeadSimpleGetPropertyConfig(LeadSimpleInput):
    """Returns an individual property."""
    operation: Literal["get_property"] = Field("get_property", json_schema_extra={"ui:hidden": True})
    property_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

class LeadSimpleUpdatePropertyConfig(LeadSimpleInput):
    """Updates a property."""
    operation: Literal["update_property"] = Field("update_property", json_schema_extra={"ui:hidden": True})
    property_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    address_city: str | None = Field(None, max_length=20000, description='The property address city')
    address_line_1: str | None = Field(None, max_length=20000, description='The property address line 1')
    address_state: str | None = Field(None, max_length=20000, description='The property address state')
    address_zip_code: str | None = Field(None, max_length=20000, description='The property address zip code')
    property_type: str | None = Field(None, max_length=20000, description='The type of property')
    tags: list[str] | None = Field(None, max_length=200, description='Tags to assign to property', json_schema_extra={"ui:widget": "list"})


LeadSimpleConfig = Annotated[Union[
    LeadSimpleGetAccountConfig,
    LeadSimpleGetUserConfig,
    LeadSimpleListContactsConfig,
    LeadSimpleCreateContactConfig,
    LeadSimpleUpdateContactConfig,
    LeadSimpleListDealsConfig,
    LeadSimpleGetDealConfig,
    LeadSimpleCreateDealConfig,
    LeadSimpleUpdateDealConfig,
    LeadSimpleListProcessesConfig,
    LeadSimpleGetProcessConfig,
    LeadSimpleCreateProcessConfig,
    LeadSimpleUpdateProcessConfig,
    LeadSimpleCreateNoteConfig,
    LeadSimpleListPipelinesConfig,
    LeadSimpleGetPipelineConfig,
    LeadSimpleListPipelineStagesConfig,
    LeadSimpleListPipelineSourcesConfig,
    LeadSimpleListProcessTypesConfig,
    LeadSimpleListProcessTypeStagesConfig,
    LeadSimpleListUsersConfig,
    LeadSimpleListPropertiesConfig,
    LeadSimpleGetPropertyConfig,
    LeadSimpleUpdatePropertyConfig,
], Field(discriminator="operation")]


class LeadSimpleFullConfig(NodeConfig[LeadSimpleConfig, LeadSimpleTokenCredential]):
    pass


# Fixed endpoint and form-key mappings from the published v1.0.0 contract.
ROUTES = {'get_account': {'method': 'GET',
                 'path': '/info/account',
                 'path_fields': [],
                 'query_fields': [],
                 'body_fields': {},
                 'status': 200},
 'get_user': {'method': 'GET',
              'path': '/info/user',
              'path_fields': [],
              'query_fields': [],
              'body_fields': {},
              'status': 200},
 'list_contacts': {'method': 'GET',
                   'path': '/contacts',
                   'path_fields': [],
                   'query_fields': ['page',
                                    'per_page',
                                    'search',
                                    'updated_since',
                                    'include_custom_fields'],
                   'body_fields': {},
                   'status': 200},
 'create_contact': {'method': 'POST',
                    'path': '/contacts',
                    'path_fields': [],
                    'query_fields': [],
                    'body_fields': {'first_name': 'first_name',
                                    'last_name': 'last_name',
                                    'company_name': 'company_name',
                                    'email_addresses': 'email_addresses[]',
                                    'tags': 'tags[]',
                                    'mailing_address': 'mailing_address',
                                    'mailing_city': 'mailing_city',
                                    'mailing_state': 'mailing_state',
                                    'mailing_zip_code': 'mailing_zip_code'},
                    'status': 201},
 'update_contact': {'method': 'PUT',
                    'path': '/contacts/{contact_id}',
                    'path_fields': ['contact_id'],
                    'query_fields': [],
                    'body_fields': {'first_name': 'first_name',
                                    'last_name': 'last_name',
                                    'company_name': 'company_name',
                                    'email_addresses': 'email_addresses[]',
                                    'tags': 'tags[]',
                                    'mailing_address': 'mailing_address',
                                    'mailing_city': 'mailing_city',
                                    'mailing_state': 'mailing_state',
                                    'mailing_zip_code': 'mailing_zip_code',
                                    'secondary_name': 'secondary_name'},
                    'status': 200},
 'list_deals': {'method': 'GET',
                'path': '/deals',
                'path_fields': [],
                'query_fields': ['page',
                                 'per_page',
                                 'pipeline_id',
                                 'search',
                                 'include_custom_fields',
                                 'updated_since'],
                'body_fields': {},
                'status': 200},
 'get_deal': {'method': 'GET',
              'path': '/deals/{deal_id}',
              'path_fields': ['deal_id'],
              'query_fields': ['include_custom_fields'],
              'body_fields': {},
              'status': 200},
 'create_deal': {'method': 'POST',
                 'path': '/deals',
                 'path_fields': [],
                 'query_fields': [],
                 'body_fields': {'deal_pipeline_id': 'deal[pipeline_id]',
                                 'deal_name': 'deal[name]',
                                 'deal_stage_id': 'deal[stage_id]',
                                 'deal_assignee_id': 'deal[assignee_id]',
                                 'deal_source_id_or_name': 'deal[source_id_or_name]',
                                 'deal_comments': 'deal[comments]',
                                 'deal_value': 'deal[value]',
                                 'deal_cost': 'deal[cost]',
                                 'deal_tags': 'deal[tags][]',
                                 'contact_full_name': 'contact[full_name]',
                                 'contact_email_addresses': 'contact[email_addresses][]',
                                 'deal_accept_duplicates': 'deal[accept_duplicates]'},
                 'status': 201},
 'update_deal': {'method': 'PUT',
                 'path': '/deals/{deal_id}',
                 'path_fields': ['deal_id'],
                 'query_fields': [],
                 'body_fields': {'pipeline_id': 'pipeline_id',
                                 'name': 'name',
                                 'stage_id': 'stage_id',
                                 'assignee_id': 'assignee_id',
                                 'comments': 'comments',
                                 'value': 'value',
                                 'cost': 'cost',
                                 'tags': 'tags[]',
                                 'remove_tags': 'remove_tags',
                                 'contact_ids': 'contact_ids[]',
                                 'property_ids': 'property_ids[]',
                                 'closed_at': 'closed_at'},
                 'status': 200},
 'list_processes': {'method': 'GET',
                    'path': '/processes',
                    'path_fields': [],
                    'query_fields': ['page',
                                     'per_page',
                                     'process_type_id',
                                     'search',
                                     'include_custom_fields',
                                     'include_property_groups',
                                     'updated_since'],
                    'body_fields': {},
                    'status': 200},
 'get_process': {'method': 'GET',
                 'path': '/processes/{process_id}',
                 'path_fields': ['process_id'],
                 'query_fields': ['include_custom_fields', 'include_property_groups'],
                 'body_fields': {},
                 'status': 200},
 'create_process': {'method': 'POST',
                    'path': '/processes',
                    'path_fields': [],
                    'query_fields': [],
                    'body_fields': {'process_process_type_id': 'process[process_type_id]',
                                    'process_stage_id': 'process[stage_id]',
                                    'process_name': 'process[name]',
                                    'process_comments': 'process[comments]',
                                    'process_due_at': 'process[due_at]',
                                    'process_user_id': 'process[user_id]',
                                    'process_tags': 'process[tags][]',
                                    'property_ids': 'property_ids[]',
                                    'unit_ids': 'unit_ids[]'},
                    'status': 201},
 'update_process': {'method': 'PUT',
                    'path': '/processes/{process_id}',
                    'path_fields': ['process_id'],
                    'query_fields': [],
                    'body_fields': {'name': 'name',
                                    'comments': 'comments',
                                    'due_at': 'due_at',
                                    'stage_id': 'stage_id',
                                    'user_id': 'user_id',
                                    'tags': 'tags[]',
                                    'remove_tags': 'remove_tags',
                                    'closed_at': 'closed_at'},
                    'status': 200},
 'create_note': {'method': 'POST',
                 'path': '/notes',
                 'path_fields': [],
                 'query_fields': [],
                 'body_fields': {'created_at': 'created_at',
                                 'description': 'description',
                                 'direction': 'direction',
                                 'kind': 'kind',
                                 'parent_id': 'parent_id',
                                 'parent_type': 'parent_type',
                                 'user_id': 'user_id'},
                 'status': 201},
 'list_pipelines': {'method': 'GET',
                    'path': '/pipelines',
                    'path_fields': [],
                    'query_fields': ['page', 'per_page', 'account_id'],
                    'body_fields': {},
                    'status': 200},
 'get_pipeline': {'method': 'GET',
                  'path': '/pipelines/{pipeline_id}',
                  'path_fields': ['pipeline_id'],
                  'query_fields': [],
                  'body_fields': {},
                  'status': 200},
 'list_pipeline_stages': {'method': 'GET',
                          'path': '/pipelines/{pipeline_id}/stages',
                          'path_fields': ['pipeline_id'],
                          'query_fields': ['page', 'per_page'],
                          'body_fields': {},
                          'status': 200},
 'list_pipeline_sources': {'method': 'GET',
                           'path': '/pipelines/{pipeline_id}/sources',
                           'path_fields': ['pipeline_id'],
                           'query_fields': ['page', 'per_page'],
                           'body_fields': {},
                           'status': 200},
 'list_process_types': {'method': 'GET',
                        'path': '/process_types',
                        'path_fields': [],
                        'query_fields': ['page', 'per_page'],
                        'body_fields': {},
                        'status': 200},
 'list_process_type_stages': {'method': 'GET',
                              'path': '/process_types/{process_type_id}/stages',
                              'path_fields': ['process_type_id'],
                              'query_fields': ['page', 'per_page'],
                              'body_fields': {},
                              'status': 200},
 'list_users': {'method': 'GET',
                'path': '/users',
                'path_fields': [],
                'query_fields': ['page', 'per_page', 'search'],
                'body_fields': {},
                'status': 200},
 'list_properties': {'method': 'GET',
                     'path': '/properties',
                     'path_fields': [],
                     'query_fields': ['page',
                                      'per_page',
                                      'search',
                                      'updated_since',
                                      'include_custom_fields',
                                      'include_property_groups'],
                     'body_fields': {},
                     'status': 200},
 'get_property': {'method': 'GET',
                  'path': '/properties/{property_id}',
                  'path_fields': ['property_id'],
                  'query_fields': [],
                  'body_fields': {},
                  'status': 200},
 'update_property': {'method': 'PUT',
                     'path': '/properties/{property_id}',
                     'path_fields': ['property_id'],
                     'query_fields': [],
                     'body_fields': {'address_city': 'address_city',
                                     'address_line_1': 'address_line_1',
                                     'address_state': 'address_state',
                                     'address_zip_code': 'address_zip_code',
                                     'property_type': 'property_type',
                                     'tags': 'tags[]'},
                     'status': 200}}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    return value


class LeadSimpleNode(WorkflowNode):
    integration_type = "automation-leadsimple"
    connection_evidence = ConnectionEvidence(noun="LeadSimple account", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return LeadSimpleFullConfig

    @staticmethod
    def _credential_family(config_data):
        credential = config_data.get("credentials")
        if isinstance(credential, dict) and "credential_type" in credential:
            if credential["credential_type"] != "leadsimple_api_token":
                raise ValueError("Attach a LeadSimple API token credential")

    @classmethod
    def parse_config(cls, config_data):
        cls._credential_family(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._credential_family(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            return {"status": "error", "error": "Connect a LeadSimple API token"}
        op = self.config.config
        route = ROUTES[op.operation]
        path = route["path"]
        for field in route["path_fields"]:
            path = path.replace("{" + field + "}", quote(getattr(op, field), safe=""))
        params = {key: getattr(op, key) for key in route["query_fields"] if getattr(op, key) is not None}
        params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in params.items()}
        form = {}
        for field, wire in route["body_fields"].items():
            value = getattr(op, field)
            if value is not None:
                if isinstance(value, bool):
                    value = str(value).lower()
                form[wire] = value
        if route["method"] != "GET" and not form:
            return {"status": "error", "error": "Provide at least one field to write"}
        headers = {"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"}
        kwargs = {"params": params, "headers": headers}
        if route["body_fields"]:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            kwargs["content"] = urlencode(form, doseq=True)
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(route["method"], BASE_URL + path, **kwargs)
        except httpx.TimeoutException:
            return {"status": "error", "error": "LeadSimple request timed out; inspect writes before retrying"}
        except httpx.HTTPError:
            return {"status": "error", "error": "LeadSimple request could not be completed; inspect writes before retrying"}
        status = response.status_code
        if status != route["status"]:
            # Keep structured provider rejection text for the shared connect verdict.
            message = "LeadSimple returned HTTP " + str(status)
            try:
                rejected = response.json()
                if isinstance(rejected, dict):
                    message = rejected.get("message") or rejected.get("error") or rejected.get("errors") or message
            except ValueError:
                pass
            return {"status": "error", "http_status": status, "error": _redact(message, credential.api_token)}
        try:
            payload = response.json()
        except ValueError:
            return {"status": "error", "http_status": status, "error": "LeadSimple returned invalid JSON"}
        if not isinstance(payload, (dict, list)):
            return {"status": "error", "http_status": status, "error": "LeadSimple returned an unexpected JSON value"}
        if isinstance(payload, dict) and (payload.get("error") or payload.get("errors")):
            return {"status": "error", "http_status": status, "error": _redact(payload.get("error") or payload["errors"], credential.api_token)}
        result = {"status": "success", "data": _redact(payload, credential.api_token), "http_status": status}
        if op.operation.startswith("list_"):
            # A page is never represented as the entire account or a proven last page.
            result["pagination"] = {"page": op.page, "per_page": op.per_page, "complete": False}
        return result
