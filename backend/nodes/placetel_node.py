"""Placetel REST API v2: one provider request per operation.

Contract: https://api.placetel.de/v2/swagger_doc (2.0.0).
Lists fetch one page; pass page/per_page explicitly to continue. Writes are
never retried automatically, including calls, SMS and outbound faxes.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.placetel.de/v2"


class PlacetelAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Placetel API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://web.placetel.de/integrations/web_api",
            "x-credential-instructions": "Copy your API key from Placetel's Web API integration settings. Paste the key without the Bearer prefix. Your existing API v1 key also works. NoClick checks the current API user; operations depend on your Placetel plan and permissions.",
        })
    credential_type: Literal["placetel_api_key"] = Field("placetel_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, min_length=1,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_api_key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without a header or spaces")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class GetMeConfig(_Operation):
    """Me."""
    operation: Literal['get_me'] = Field('get_me', title='Get Me', json_schema_extra={"ui:hidden": True})


class ListContactsConfig(_Operation):
    """Get all contacts."""
    operation: Literal['list_contacts'] = Field('list_contacts', title='List Contacts', json_schema_extra={"ui:hidden": True})
    filter_speeddial: int | None = Field(None, title='Filter Speeddial')
    filter_first_name: str | None = Field(None, title='Filter First Name')
    filter_last_name: str | None = Field(None, title='Filter Last Name')
    filter_company: str | None = Field(None, title='Filter Company')
    filter_email: str | None = Field(None, title='Filter Email')
    filter_email_work: str | None = Field(None, title='Filter Email Work')
    filter_phone_work: str | None = Field(None, title='Filter Phone Work')
    filter_mobile_work: str | None = Field(None, title='Filter Mobile Work')
    filter_phone: str | None = Field(None, title='Filter Phone')
    filter_mobile: str | None = Field(None, title='Filter Mobile')
    filter_blocked: bool | None = Field(None, title='Filter Blocked')
    filter_updated_at_gte: datetime | None = Field(None, title='Filter Updated At Gte')
    filter_updated_at_lte: datetime | None = Field(None, title='Filter Updated At Lte')
    search_number: str | None = Field(None, title='Search Number')
    page: int = Field(1, title='Page', ge=1, description='Page of results to fetch.')
    per_page: int = Field(25, title='Per Page', ge=1, le=100, description='Number of results to return per page.')


class GetContactConfig(_Operation):
    """Retrieve a contact."""
    operation: Literal['get_contact'] = Field('get_contact', title='Get Contact', json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., title='Contact Id', ge=1, description='ID of a contact')


class CreateContactConfig(_Operation):
    """Create a contact."""
    operation: Literal['create_contact'] = Field('create_contact', title='Create Contact', json_schema_extra={"ui:hidden": True})
    speeddial: str | None = Field(None, title='Speeddial')
    first_name: str | None = Field(None, title='First Name')
    last_name: str | None = Field(None, title='Last Name')
    email: str | None = Field(None, title='Email')
    email_work: str | None = Field(None, title='Email Work')
    company: str | None = Field(None, title='Company')
    address: str | None = Field(None, title='Address')
    address_work: str | None = Field(None, title='Address Work')
    phone_work: str | None = Field(None, title='Phone Work')
    mobile_work: str | None = Field(None, title='Mobile Work')
    phone: str | None = Field(None, title='Phone')
    mobile: str | None = Field(None, title='Mobile')
    fax: str | None = Field(None, title='Fax')
    fax_work: str | None = Field(None, title='Fax Work')
    facebook_url: str | None = Field(None, title='Facebook Url')
    linkedin_url: str | None = Field(None, title='Linkedin Url')
    xing_url: str | None = Field(None, title='Xing Url')
    twitter_account: str | None = Field(None, title='Twitter Account')
    color: str | None = Field(None, title='Color')
    tags: list[str] | None = Field(None, title='Tags')
    user_id: int | None = Field(None, title='User Id')
    blocked: bool | None = Field(None, title='Blocked')


class UpdateContactConfig(_Operation):
    """Update a contact."""
    operation: Literal['update_contact'] = Field('update_contact', title='Update Contact', json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., title='Contact Id', ge=1, description='Contact ID')
    speeddial: str | None = Field(None, title='Speeddial')
    first_name: str | None = Field(None, title='First Name')
    last_name: str | None = Field(None, title='Last Name')
    email: str | None = Field(None, title='Email')
    email_work: str | None = Field(None, title='Email Work')
    company: str | None = Field(None, title='Company')
    address: str | None = Field(None, title='Address')
    address_work: str | None = Field(None, title='Address Work')
    phone_work: str | None = Field(None, title='Phone Work')
    mobile_work: str | None = Field(None, title='Mobile Work')
    phone: str | None = Field(None, title='Phone')
    mobile: str | None = Field(None, title='Mobile')
    fax: str | None = Field(None, title='Fax')
    fax_work: str | None = Field(None, title='Fax Work')
    facebook_url: str | None = Field(None, title='Facebook Url')
    linkedin_url: str | None = Field(None, title='Linkedin Url')
    xing_url: str | None = Field(None, title='Xing Url')
    twitter_account: str | None = Field(None, title='Twitter Account')
    color: str | None = Field(None, title='Color')
    tags: list[str] | None = Field(None, title='Tags')
    user_id: int | None = Field(None, title='User Id')
    blocked: bool | None = Field(None, title='Blocked')


class DeleteContactConfig(_Operation):
    """Deletes a contact."""
    operation: Literal['delete_contact'] = Field('delete_contact', title='Delete Contact', json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., title='Contact Id', ge=1, description='Contact ID')


class ListCallsConfig(_Operation):
    """Fetch all incoming calls."""
    operation: Literal['list_calls'] = Field('list_calls', title='List Calls', json_schema_extra={"ui:hidden": True})
    filter_date: date | None = Field(None, title='Filter Date', description='YYYY-MM-DD, defaults to today.')
    filter_from_number: str | None = Field(None, title='Filter From Number')
    filter_to_number: str | None = Field(None, title='Filter To Number')
    filter_type: Literal['voicemail', 'missed', 'blocked', 'accepted', 'voicemail,missed', 'missed,blocked,accepted'] | None = Field(None, title='Filter Type')
    order: Literal['asc', 'desc'] | None = Field(None, title='Order')
    page: int = Field(1, title='Page', ge=1, description='Page of results to fetch.')
    per_page: int = Field(25, title='Per Page', ge=1, le=100, description='Number of results to return per page.')


class GetCallConfig(_Operation):
    """Retrieve a call."""
    operation: Literal['get_call'] = Field('get_call', title='Get Call', json_schema_extra={"ui:hidden": True})
    call_id: int = Field(..., title='Call Id', ge=1, description='Call ID')


class InitiateCallConfig(_Operation):
    """Initiate a call."""
    operation: Literal['initiate_call'] = Field('initiate_call', title='Initiate Call', json_schema_extra={"ui:hidden": True})
    sipuid: str = Field(..., title='Sipuid', description='Sipuid to use (e.g. 7771234567@fpbx.de)')
    target: str = Field(..., title='Target', description='Number to call')
    from_name: str | None = Field(None, title='From Name')


class DeleteCallConfig(_Operation):
    """Delete a call."""
    operation: Literal['delete_call'] = Field('delete_call', title='Delete Call', json_schema_extra={"ui:hidden": True})
    call_id: int = Field(..., title='Call Id', ge=1, description='Call ID')


class ListNumbersConfig(_Operation):
    """Get all numbers."""
    operation: Literal['list_numbers'] = Field('list_numbers', title='List Numbers', json_schema_extra={"ui:hidden": True})
    filter_prefix: str | None = Field(None, title='Filter Prefix')
    filter_number: str | None = Field(None, title='Filter Number')
    filter_activated: bool | None = Field(None, title='Filter Activated', description='Only relevant for Profi customers')
    filter_name: str | None = Field(None, title='Filter Name')
    filter_description: str | None = Field(None, title='Filter Description')
    filter_site_id: int | None = Field(None, title='Filter Site Id')
    page: int = Field(1, title='Page', ge=1, description='Page of results to fetch.')
    per_page: int = Field(25, title='Per Page', ge=1, le=100, description='Number of results to return per page.')


class GetNumberConfig(_Operation):
    """Retrieve a number."""
    operation: Literal['get_number'] = Field('get_number', title='Get Number', json_schema_extra={"ui:hidden": True})
    number_id: int = Field(..., title='Number Id', ge=1, description='Number ID')


class ListSipUsersConfig(_Operation):
    """Fetch all sip users."""
    operation: Literal['list_sip_users'] = Field('list_sip_users', title='List Sip Users', json_schema_extra={"ui:hidden": True})
    filter_did: int | None = Field(None, title='Filter Did')
    filter_username: str | None = Field(None, title='Filter Username')
    filter_name: str | None = Field(None, title='Filter Name')
    filter_description: str | None = Field(None, title='Filter Description')
    page: int = Field(1, title='Page', ge=1, description='Page of results to fetch.')
    per_page: int = Field(25, title='Per Page', ge=1, le=100, description='Number of results to return per page.')


class GetSipUserConfig(_Operation):
    """Fetch a sip user."""
    operation: Literal['get_sip_user'] = Field('get_sip_user', title='Get Sip User', json_schema_extra={"ui:hidden": True})
    sip_user_id: int = Field(..., title='Sip User Id', ge=1, description='Sip user ID')


class ListGroupsConfig(_Operation):
    """Fetch all groups."""
    operation: Literal['list_groups'] = Field('list_groups', title='List Groups', json_schema_extra={"ui:hidden": True})
    filter_name: str | None = Field(None, title='Filter Name')
    filter_description: str | None = Field(None, title='Filter Description')
    filter_type: Literal['ring_all', 'monitoring', 'hunt'] | None = Field(None, title='Filter Type')
    page: int = Field(1, title='Page', ge=1, description='Page of results to fetch.')
    per_page: int = Field(25, title='Per Page', ge=1, le=100, description='Number of results to return per page.')


class GetGroupConfig(_Operation):
    """Fetch a group."""
    operation: Literal['get_group'] = Field('get_group', title='Get Group', json_schema_extra={"ui:hidden": True})
    group_id: int = Field(..., title='Group Id', ge=1, description='Group ID')


class CreateGroupConfig(_Operation):
    """Create a group."""
    operation: Literal['create_group'] = Field('create_group', title='Create Group', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., title='Name')
    type: Literal['ring_all', 'monitoring', 'hunt'] = Field(..., title='Type')
    description: str | None = Field(None, title='Description')
    member_ids: list[int] | None = Field(None, title='Member Ids', description='Array of SipUser ids')


class UpdateGroupConfig(_Operation):
    """Update a group."""
    operation: Literal['update_group'] = Field('update_group', title='Update Group', json_schema_extra={"ui:hidden": True})
    group_id: int = Field(..., title='Group Id', ge=1, description='Group ID')
    name: str | None = Field(None, title='Name')
    description: str | None = Field(None, title='Description')
    member_ids: list[int] | None = Field(None, title='Member Ids', description='Array of SipUser ids')


class DeleteGroupConfig(_Operation):
    """Delete a group."""
    operation: Literal['delete_group'] = Field('delete_group', title='Delete Group', json_schema_extra={"ui:hidden": True})
    group_id: int = Field(..., title='Group Id', ge=1, description='Group ID')


class ListRecordingsConfig(_Operation):
    """Fetch call recordings."""
    operation: Literal['list_recordings'] = Field('list_recordings', title='List Recordings', json_schema_extra={"ui:hidden": True})
    filter_direction: list[str] | None = Field(None, title='Filter Direction')
    filter_from: str | None = Field(None, title='Filter From')
    filter_to: str | None = Field(None, title='Filter To')
    filter_date: date | None = Field(None, title='Filter Date', description='YYYY-MM-DD')
    order: Literal['asc', 'desc'] | None = Field(None, title='Order')
    page: int = Field(1, title='Page', ge=1, description='Page of results to fetch.')
    per_page: int = Field(25, title='Per Page', ge=1, le=100, description='Number of results to return per page.')


class GetRecordingConfig(_Operation):
    """Fetch specific recording."""
    operation: Literal['get_recording'] = Field('get_recording', title='Get Recording', json_schema_extra={"ui:hidden": True})
    recording_id: int = Field(..., title='Recording Id', ge=1, description='Recording ID')


class ListFaxesConfig(_Operation):
    """Fetch in- and outbound faxes."""
    operation: Literal['list_faxes'] = Field('list_faxes', title='List Faxes', json_schema_extra={"ui:hidden": True})
    filter_type: Literal['inbound,outbound', 'inbound', 'outbound'] | None = Field(None, title='Filter Type')
    filter_from_number: str | None = Field(None, title='Filter From Number')
    filter_to_number: str | None = Field(None, title='Filter To Number')
    order: Literal['asc', 'desc'] | None = Field(None, title='Order')
    page: int = Field(1, title='Page', ge=1, description='Page of results to fetch.')
    per_page: int = Field(25, title='Per Page', ge=1, le=100, description='Number of results to return per page.')


class GetFaxConfig(_Operation):
    """Fetch specific fax."""
    operation: Literal['get_fax'] = Field('get_fax', title='Get Fax', json_schema_extra={"ui:hidden": True})
    fax_id: int = Field(..., title='Fax Id', ge=1, description='Fax ID')


class SendFaxConfig(_Operation):
    """Create outbound fax."""
    operation: Literal['send_fax'] = Field('send_fax', title='Send Fax', json_schema_extra={"ui:hidden": True})
    from_number: str = Field(..., title='From Number')
    to_number: str = Field(..., title='To Number')
    email: str = Field(..., title='Email')
    file: str = Field(..., title='File', description='Base64 encoded PDF file as [data uri](https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/Data_URIs)')
    header: str | None = Field(None, title='Header')


class SendSmsConfig(_Operation):
    """Send SMS."""
    operation: Literal['send_sms'] = Field('send_sms', title='Send Sms', json_schema_extra={"ui:hidden": True})
    recipient: str = Field(..., title='Recipient', description='Number to send message to')
    message: str = Field(..., title='Message', description='Your message')


Operation = Annotated[Union[
    GetMeConfig,
    ListContactsConfig,
    GetContactConfig,
    CreateContactConfig,
    UpdateContactConfig,
    DeleteContactConfig,
    ListCallsConfig,
    GetCallConfig,
    InitiateCallConfig,
    DeleteCallConfig,
    ListNumbersConfig,
    GetNumberConfig,
    ListSipUsersConfig,
    GetSipUserConfig,
    ListGroupsConfig,
    GetGroupConfig,
    CreateGroupConfig,
    UpdateGroupConfig,
    DeleteGroupConfig,
    ListRecordingsConfig,
    GetRecordingConfig,
    ListFaxesConfig,
    GetFaxConfig,
    SendFaxConfig,
    SendSmsConfig
], Field(discriminator="operation")]


class PlacetelNodeConfig(NodeConfig[Operation, PlacetelAPIKeyCredential]):
    pass


OPERATIONS = {'get_me': {'method': 'GET',
            'path': '/me',
            'id_field': None,
            'query': {},
            'body': [],
            'status': 200,
            'list': False,
            'response_body': True},
 'list_contacts': {'method': 'GET',
                   'path': '/contacts',
                   'id_field': None,
                   'query': {'filter_speeddial': 'filter[speeddial]',
                             'filter_first_name': 'filter[first_name]',
                             'filter_last_name': 'filter[last_name]',
                             'filter_company': 'filter[company]',
                             'filter_email': 'filter[email]',
                             'filter_email_work': 'filter[email_work]',
                             'filter_phone_work': 'filter[phone_work]',
                             'filter_mobile_work': 'filter[mobile_work]',
                             'filter_phone': 'filter[phone]',
                             'filter_mobile': 'filter[mobile]',
                             'filter_blocked': 'filter[blocked]',
                             'filter_updated_at_gte': 'filter[updated_at_gte]',
                             'filter_updated_at_lte': 'filter[updated_at_lte]',
                             'search_number': 'search[number]',
                             'page': 'page',
                             'per_page': 'per_page'},
                   'body': [],
                   'status': 200,
                   'list': True,
                   'response_body': True},
 'get_contact': {'method': 'GET',
                 'path': '/contacts/{id}',
                 'id_field': 'contact_id',
                 'query': {},
                 'body': [],
                 'status': 200,
                 'list': False,
                 'response_body': True},
 'create_contact': {'method': 'POST',
                    'path': '/contacts',
                    'id_field': None,
                    'query': {},
                    'body': ['speeddial',
                             'first_name',
                             'last_name',
                             'email',
                             'email_work',
                             'company',
                             'address',
                             'address_work',
                             'phone_work',
                             'mobile_work',
                             'phone',
                             'mobile',
                             'fax',
                             'fax_work',
                             'facebook_url',
                             'linkedin_url',
                             'xing_url',
                             'twitter_account',
                             'color',
                             'tags',
                             'user_id',
                             'blocked'],
                    'status': 201,
                    'list': False,
                    'response_body': True},
 'update_contact': {'method': 'PUT',
                    'path': '/contacts/{id}',
                    'id_field': 'contact_id',
                    'query': {},
                    'body': ['speeddial',
                             'first_name',
                             'last_name',
                             'email',
                             'email_work',
                             'company',
                             'address',
                             'address_work',
                             'phone_work',
                             'mobile_work',
                             'phone',
                             'mobile',
                             'fax',
                             'fax_work',
                             'facebook_url',
                             'linkedin_url',
                             'xing_url',
                             'twitter_account',
                             'color',
                             'tags',
                             'user_id',
                             'blocked'],
                    'status': 200,
                    'list': False,
                    'response_body': True},
 'delete_contact': {'method': 'DELETE',
                    'path': '/contacts/{id}',
                    'id_field': 'contact_id',
                    'query': {},
                    'body': [],
                    'status': 204,
                    'list': False,
                    'response_body': False},
 'list_calls': {'method': 'GET',
                'path': '/calls',
                'id_field': None,
                'query': {'filter_date': 'filter[date]',
                          'filter_from_number': 'filter[from_number]',
                          'filter_to_number': 'filter[to_number]',
                          'filter_type': 'filter[type]',
                          'order': 'order',
                          'page': 'page',
                          'per_page': 'per_page'},
                'body': [],
                'status': 200,
                'list': True,
                'response_body': True},
 'get_call': {'method': 'GET',
              'path': '/calls/{id}',
              'id_field': 'call_id',
              'query': {},
              'body': [],
              'status': 200,
              'list': False,
              'response_body': True},
 'initiate_call': {'method': 'POST',
                   'path': '/calls',
                   'id_field': None,
                   'query': {},
                   'body': ['sipuid', 'target', 'from_name'],
                   'status': 201,
                   'list': False,
                   'response_body': True},
 'delete_call': {'method': 'DELETE',
                 'path': '/calls/{id}',
                 'id_field': 'call_id',
                 'query': {},
                 'body': [],
                 'status': 204,
                 'list': False,
                 'response_body': False},
 'list_numbers': {'method': 'GET',
                  'path': '/numbers',
                  'id_field': None,
                  'query': {'filter_prefix': 'filter[prefix]',
                            'filter_number': 'filter[number]',
                            'filter_activated': 'filter[activated]',
                            'filter_name': 'filter[name]',
                            'filter_description': 'filter[description]',
                            'filter_site_id': 'filter[site_id]',
                            'page': 'page',
                            'per_page': 'per_page'},
                  'body': [],
                  'status': 200,
                  'list': True,
                  'response_body': True},
 'get_number': {'method': 'GET',
                'path': '/numbers/{id}',
                'id_field': 'number_id',
                'query': {},
                'body': [],
                'status': 200,
                'list': False,
                'response_body': True},
 'list_sip_users': {'method': 'GET',
                    'path': '/sip_users',
                    'id_field': None,
                    'query': {'filter_did': 'filter[did]',
                              'filter_username': 'filter[username]',
                              'filter_name': 'filter[name]',
                              'filter_description': 'filter[description]',
                              'page': 'page',
                              'per_page': 'per_page'},
                    'body': [],
                    'status': 200,
                    'list': True,
                    'response_body': True},
 'get_sip_user': {'method': 'GET',
                  'path': '/sip_users/{id}',
                  'id_field': 'sip_user_id',
                  'query': {},
                  'body': [],
                  'status': 200,
                  'list': False,
                  'response_body': True},
 'list_groups': {'method': 'GET',
                 'path': '/groups',
                 'id_field': None,
                 'query': {'filter_name': 'filter[name]',
                           'filter_description': 'filter[description]',
                           'filter_type': 'filter[type]',
                           'page': 'page',
                           'per_page': 'per_page'},
                 'body': [],
                 'status': 200,
                 'list': True,
                 'response_body': True},
 'get_group': {'method': 'GET',
               'path': '/groups/{id}',
               'id_field': 'group_id',
               'query': {},
               'body': [],
               'status': 200,
               'list': False,
               'response_body': True},
 'create_group': {'method': 'POST',
                  'path': '/groups',
                  'id_field': None,
                  'query': {},
                  'body': ['name', 'type', 'description', 'member_ids'],
                  'status': 201,
                  'list': False,
                  'response_body': True},
 'update_group': {'method': 'PUT',
                  'path': '/groups/{id}',
                  'id_field': 'group_id',
                  'query': {},
                  'body': ['name', 'description', 'member_ids'],
                  'status': 200,
                  'list': False,
                  'response_body': True},
 'delete_group': {'method': 'DELETE',
                  'path': '/groups/{id}',
                  'id_field': 'group_id',
                  'query': {},
                  'body': [],
                  'status': 204,
                  'list': False,
                  'response_body': False},
 'list_recordings': {'method': 'GET',
                     'path': '/recordings',
                     'id_field': None,
                     'query': {'filter_direction': 'filter[direction]',
                               'filter_from': 'filter[from]',
                               'filter_to': 'filter[to]',
                               'filter_date': 'filter[date]',
                               'order': 'order',
                               'page': 'page',
                               'per_page': 'per_page'},
                     'body': [],
                     'status': 200,
                     'list': True,
                     'response_body': True},
 'get_recording': {'method': 'GET',
                   'path': '/recordings/{id}',
                   'id_field': 'recording_id',
                   'query': {},
                   'body': [],
                   'status': 200,
                   'list': False,
                   'response_body': True},
 'list_faxes': {'method': 'GET',
                'path': '/faxes',
                'id_field': None,
                'query': {'filter_type': 'filter[type]',
                          'filter_from_number': 'filter[from_number]',
                          'filter_to_number': 'filter[to_number]',
                          'order': 'order',
                          'page': 'page',
                          'per_page': 'per_page'},
                'body': [],
                'status': 200,
                'list': True,
                'response_body': True},
 'get_fax': {'method': 'GET',
             'path': '/faxes/{id}',
             'id_field': 'fax_id',
             'query': {},
             'body': [],
             'status': 200,
             'list': False,
             'response_body': True},
 'send_fax': {'method': 'POST',
              'path': '/faxes',
              'id_field': None,
              'query': {},
              'body': ['from_number', 'to_number', 'email', 'file', 'header'],
              'status': 201,
              'list': False,
              'response_body': True},
 'send_sms': {'method': 'POST',
              'path': '/sms',
              'id_field': None,
              'query': {},
              'body': ['recipient', 'message'],
              'status': 201,
              'list': False,
              'response_body': False}}


class PlacetelNode(WorkflowNode):
    integration_type = "automation-placetel"
    connection_evidence = ConnectionEvidence(noun="Placetel account", identity_operation="get_me")

    @classmethod
    def get_config_model(cls):
        return PlacetelNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Placetel API key")
        config = self.config.config
        credential = self.config.credentials
        spec = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        path = spec["path"]
        if spec["id_field"]:
            path = path.replace("{id}", str(values[spec["id_field"]]))
        params = {wire: values[name] for name, wire in spec["query"].items() if name in values}
        # Swagger 2 query arrays default to CSV (collectionFormat is omitted).
        params = {k: ",".join(map(str, v)) if isinstance(v, list) else
            ("true" if v else "false") if isinstance(v, bool) else v for k, v in params.items()}
        body = {name: values[name] for name in spec["body"] if name in values}
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(spec["method"], BASE_URL + path,
                    headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"},
                    params=params, **({"json": body} if spec["method"] in {"POST", "PUT"} else {}))
        except httpx.HTTPError:
            return {"status": "error", "success": False,
                "error": "Placetel request did not complete. Check the provider before retrying a write.",
                "write_outcome": "unknown" if spec["method"] != "GET" else None}
        if response.status_code != spec["status"]:
            # Preserve the provider's rejection while refusing credential reflection.
            message = response.text[:2000].replace(credential.api_key, "[redacted]")
            return {"status": "error", "success": False, "status_code": response.status_code,
                "error": message or "Placetel returned an unexpected status",
                "write_outcome": "unknown" if spec["method"] != "GET" and (response.status_code < 400 or response.status_code >= 500) else None}
        payload = None
        if response.content.strip():
            try:
                payload = response.json()
            except ValueError:
                return {"status": "error", "success": False, "error": "Placetel returned invalid JSON"}
        if spec["response_body"]:
            expected = list if spec["list"] else dict
            if not isinstance(payload, expected):
                return {"status": "error", "success": False, "error": "Placetel returned an unexpected response shape"}
            if isinstance(payload, dict) and (payload.get("error") or payload.get("errors")):
                return {"status": "error", "success": False,
                    "error": str(payload.get("error") or payload["errors"])[:2000].replace(credential.api_key, "[redacted]")}
        return {"status": "success", "success": True, "data": payload, "status_code": response.status_code}
