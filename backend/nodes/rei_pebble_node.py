"""REI Pebble account reads and writes using a user-supplied API key.

Each operation issues one request against Pebble's published v1 contract.
Pagination is explicit: callers request the next page using returned metadata.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
import re
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.pebblerei.com"
CREDENTIAL_TYPE = "rei_pebble_api_key"


class REIPebbleAPIKey(BaseModel):
    model_config = ConfigDict(title="REI Pebble API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://kb.pebblerei.com/article/449-pebble-api",
            "x-credential-instructions": "An account admin can generate a key in Account Settings → Integrations → API → Add API Key. Paste the key here without the Bearer prefix."})
    credential_type: Literal["rei_pebble_api_key"] = Field("rei_pebble_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without spaces or the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def valid_parameters(self):
        for name, value in self.__dict__.items():
            if (name == "id" or name.endswith("_id")) and value is not None:
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,254}", value):
                    raise ValueError("Use a single Pebble resource identifier")
        if "dir" in type(self).model_fields and getattr(self, "sort", None) and not getattr(self, "dir", None):
            raise ValueError("Select a direction when sorting")
        return self


class GetCurrentUser(_Input):
    """Show current user."""
    operation: Literal['get_current_user'] = Field('get_current_user', title='Show current user', json_schema_extra={"ui:hidden": True})


class ListContacts(_Input):
    """List contacts."""
    operation: Literal['list_contacts'] = Field('list_contacts', title='List contacts', json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, description='Case insensitive partial match against the contact name. A value shorter than\nthree characters is ignored and every contact is returned.')
    has_phone: bool | None = Field(None, description='Set to `true` to return only contacts that have a primary phone number. Sending\n`false` has no effect.')
    has_email: bool | None = Field(None, description='Set to `true` to return only contacts that have an email address. Sending\n`false` has no effect.')
    email: str | None = Field(None, description="Case insensitive partial match against the contact's email address. A value\nshorter than three characters is ignored and every contact is returned.")
    phone: str | None = Field(None, description="Partial match against the contact's phone numbers. A value shorter than three\ncharacters is ignored and every contact is returned.")
    category: Literal['buyer', 'seller', 'attorney', 'banker', 'builder', 'contractor', 'developer', 'funder', 'municipal_officer', 'notary', 'photographer', 'real_estate_agent', 'surveyor', 'title_agent', 'other'] | None = Field(None, description='Return only contacts with this category')
    tag_ids: list[str] | None = Field(None, description='Return only contacts tagged with any of these tags. Accepts either a single\nidentifier or the `tag_ids[]=a&tag_ids[]=b` form.')
    do_not_mail: bool | None = Field(None, description='Set to `true` to return only contacts who have opted out of mail, `false` for\nonly those who have not.')
    has_deal: bool | None = Field(None, description='Set to `true` for only contacts with an associated deal, `false` for only those without')
    deal_status: Literal['open', 'closed'] | None = Field(None, description='Return only contacts with a deal in this status')
    has_property: bool | None = Field(None, description='Set to `true` for only contacts with an associated property, `false` for only those without')
    property_county_ids: list[str] | None = Field(None, description='Return only contacts with a property in these counties, given as county\nidentifiers such as `harris_tx`. Accepts either a single value or the\n`property_county_ids[]=` form.')
    campaign_id: str | None = Field(None, description='Return only contacts with a campaign record on this campaign')
    campaign_record_code: str | None = Field(None, description="Case insensitive prefix match against the contact's campaign record code")
    sort: Literal['name'] | None = Field(None, description='Field to order the results by')
    page: int | None = Field(None, description='Page of results to return, starting at 1', ge=1)


class PebbleAddressParams(_Input):
    city: str | None = Field(None, description='City')
    line1: str | None = Field(None, description='First street line')
    line2: str | None = Field(None, description='Second street line, such as a unit or suite number')
    state: str | None = Field(None, description='State')
    zip: str | None = Field(None, description='Postal code')


class CreateContact(_Input):
    """Create contact."""
    operation: Literal['create_contact'] = Field('create_contact', title='Create contact', json_schema_extra={"ui:hidden": True})
    address: PebbleAddressParams | None = Field(None)
    category: Literal['buyer', 'seller', 'attorney', 'banker', 'builder', 'contractor', 'developer', 'funder', 'municipal_officer', 'notary', 'photographer', 'real_estate_agent', 'surveyor', 'title_agent', 'other'] | None = Field(None, description="Role the contact plays in the account's deals")
    description: str | None = Field(None, description='Free form notes about the contact')
    do_not_mail: bool | None = Field(None, description='Excludes the contact from future mail campaigns')
    email: str | None = Field(None, description='Email address, which must be unique across the contacts in the account')
    first_name: str | None = Field(None, description='Given name')
    last_name: str | None = Field(None, description='Family name')
    name: str = Field(..., description='Full name of the contact', max_length=255)
    phone: str | None = Field(None, description='Primary phone number')
    phone_secondary: str | None = Field(None, description='Additional phone number')


class UpdateContact(_Input):
    """Update contact."""
    operation: Literal['update_contact'] = Field('update_contact', title='Update contact', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Identifier of the contact to update', min_length=1)
    address: PebbleAddressParams | None = Field(None)
    category: Literal['buyer', 'seller', 'attorney', 'banker', 'builder', 'contractor', 'developer', 'funder', 'municipal_officer', 'notary', 'photographer', 'real_estate_agent', 'surveyor', 'title_agent', 'other'] | None = Field(None, description="Role the contact plays in the account's deals")
    description: str | None = Field(None, description='Free form notes about the contact')
    do_not_mail: bool | None = Field(None, description='Excludes the contact from future mail campaigns')
    email: str | None = Field(None, description='Email address, which must be unique across the contacts in the account')
    first_name: str | None = Field(None, description='Given name')
    last_name: str | None = Field(None, description='Family name')
    name: str = Field(..., description='Full name of the contact', max_length=255)
    phone: str | None = Field(None, description='Primary phone number')
    phone_secondary: str | None = Field(None, description='Additional phone number')


class ListDeals(_Input):
    """List deals."""
    operation: Literal['list_deals'] = Field('list_deals', title='List deals', json_schema_extra={"ui:hidden": True})
    board_id: str | None = Field(None, description='Return only the deals on this board')
    stage_id: str | None = Field(None, description='Return only the deals in this stage')
    term: str | None = Field(None, description='Case insensitive partial match against the deal title')
    status: Literal['open', 'closed'] | None = Field(None, description='Return only the deals with this status')
    priority: Literal['hot', 'warm', 'cold', 'none'] | None = Field(None, description='Return only the deals with this priority. `none` matches the deals that have no\npriority set.')
    last_activity_after: date | None = Field(None, description='Return only the deals last active on or after this date')
    last_activity_before: date | None = Field(None, description='Return only the deals last active on or before this date')
    sort: Literal['title', 'stage', 'position', 'value', 'priority', 'last_activity_at'] | None = Field(None, description='Field to order the results by. Requires `dir` to be supplied as well.')
    dir: Literal['asc', 'desc'] | None = Field(None, description='Direction to apply `sort` in. Required whenever `sort` is supplied.')
    page: int | None = Field(None, description='Page of results to return, starting at 1', ge=1)


class CreateDeal(_Input):
    """Create deal."""
    operation: Literal['create_deal'] = Field('create_deal', title='Create deal', json_schema_extra={"ui:hidden": True})
    board_id: str = Field(..., description='Identifier of the board to place the deal on', min_length=1)
    campaign_id: str | None = Field(None, description='Identifier of the campaign the deal came out of')
    contact_ids: list[str] | None = Field(None, description='Identifiers of the contacts to attach to the deal')
    property_ids: list[str] | None = Field(None, description='Identifiers of the properties to attach to the deal')
    source: Literal['direct_mail', 'cold_call', 'text', 'email', 'paid_ads', 'lead_form', 'social_media', 'referral', 'other'] | None = Field(None, description='Where the deal originated')
    stage_id: str = Field(..., description='Identifier of the stage to place the deal in', min_length=1)
    status: Literal['open', 'closed'] | None = Field(None, description='Whether the deal is still being worked')
    title: str = Field(..., description='Display name of the deal')
    value: int | None = Field(None, description='Value of the deal in cents')


class UpdateDeal(_Input):
    """Update deal."""
    operation: Literal['update_deal'] = Field('update_deal', title='Update deal', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Identifier of the deal to update', min_length=1)
    board_id: str = Field(..., description='Identifier of the board to place the deal on', min_length=1)
    campaign_id: str | None = Field(None, description='Identifier of the campaign the deal came out of')
    contact_ids: list[str] | None = Field(None, description='Identifiers of the contacts to attach to the deal')
    property_ids: list[str] | None = Field(None, description='Identifiers of the properties to attach to the deal')
    source: Literal['direct_mail', 'cold_call', 'text', 'email', 'paid_ads', 'lead_form', 'social_media', 'referral', 'other'] | None = Field(None, description='Where the deal originated')
    stage_id: str = Field(..., description='Identifier of the stage to place the deal in', min_length=1)
    status: Literal['open', 'closed'] | None = Field(None, description='Whether the deal is still being worked')
    title: str = Field(..., description='Display name of the deal')
    value: int | None = Field(None, description='Value of the deal in cents')


class ListProperties(_Input):
    """List properties."""
    operation: Literal['list_properties'] = Field('list_properties', title='List properties', json_schema_extra={"ui:hidden": True})
    ids: list[str] | None = Field(None, description='Return only these properties. Accepts either a single identifier or the\n`ids[]=a&ids[]=b` form. A malformed identifier — including an empty value —\nis rejected with a `400`.')
    county_ids: list[str] | None = Field(None, description='Return only the properties in these counties, given as county identifiers such as\n`harris_tx`. Accepts either a single value or the `county_ids[]=` form.')
    term: str | None = Field(None, description='Case insensitive partial match against the parcel number, street address and\nowner name. A term shorter than three characters is ignored and every property is\nreturned.')
    has_campaign: bool | None = Field(None, description='Set to `true` for only the properties that have been mailed, `false` for only those that have not')
    campaign_record_code: str | None = Field(None, description='Return only the properties whose campaign record code starts with this value, matched case sensitively in lower case')
    campaign_record_date_after: date | None = Field(None, description='Return only the properties mailed on or after this date')
    campaign_record_date_before: date | None = Field(None, description='Return only the properties mailed on or before this date')
    campaign_record_price_low: int | None = Field(None, description='Return only the properties offered at or above this price, in cents')
    campaign_record_price_high: int | None = Field(None, description='Return only the properties offered at or below this price, in cents')
    sort: Literal['owner', 'county', 'campaign_record_price', 'offer_price', 'purchase_price', 'sale_price', 'apn', 'acreage', 'legal_desc', 'inserted_at', 'id'] | None = Field(None, description='Field to order the results by. Requires `dir` to be supplied as well.')
    dir: Literal['asc', 'desc'] | None = Field(None, description='Direction to apply `sort` in. Required whenever `sort` is supplied.')
    page: int | None = Field(None, description='Page of results to return, starting at 1', ge=1)


class PebbleStructureInput(_Input):
    bathrooms: int | None = Field(None, description='Number of bathrooms')
    bedrooms: int | None = Field(None, description='Number of bedrooms')
    floors: int | None = Field(None, description='Number of storeys')
    square_feet: float | None = Field(None, description='Finished floor area in square feet')
    year_built: int | None = Field(None, description='Year of construction')


class CreateProperty(_Input):
    """Create property."""
    operation: Literal['create_property'] = Field('create_property', title='Create property', json_schema_extra={"ui:hidden": True})
    acreage: float | None = Field(None, description='Size of the parcel in acres')
    address: PebbleAddressParams | None = Field(None)
    apn: str = Field(..., description="Assessor's parcel number. Must be unique within the county for the account.")
    county_id: str = Field(..., description='Identifier of the county the parcel sits in, such as `harris_tx`. The `/api/counties` endpoint lists the valid values.', min_length=1)
    geometry_collection: dict | None = Field(None, description='Parcel boundary as a GeoJSON `GeometryCollection`')
    legal_desc: str | None = Field(None, description='Legal description of the parcel')
    structure: PebbleStructureInput | None = Field(None, description='The building on the parcel')


class UpdateProperty(_Input):
    """Update property."""
    operation: Literal['update_property'] = Field('update_property', title='Update property', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Identifier of the property to update', min_length=1)
    acreage: float | None = Field(None, description='Size of the parcel in acres')
    address: PebbleAddressParams | None = Field(None)
    apn: str | None = Field(None, description="Assessor's parcel number. Must be unique within the county for the account.")
    county_id: str = Field(..., description='Identifier of the county the parcel sits in, such as `harris_tx`. The `/api/counties` endpoint lists the valid values.', min_length=1)
    geometry_collection: dict | None = Field(None, description='Parcel boundary as a GeoJSON `GeometryCollection`')
    legal_desc: str | None = Field(None, description='Legal description of the parcel')
    structure: PebbleStructureInput | None = Field(None, description='The building on the parcel')


class ListBoards(_Input):
    """List boards."""
    operation: Literal['list_boards'] = Field('list_boards', title='List boards', json_schema_extra={"ui:hidden": True})
    term: str | None = Field(None, description='Case insensitive partial match against the board name')
    page: int | None = Field(None, description='Page of results to return, starting at 1', ge=1)


class ListStages(_Input):
    """List stages."""
    operation: Literal['list_stages'] = Field('list_stages', title='List stages', json_schema_extra={"ui:hidden": True})
    board_id: str | None = Field(None, description='Return only the stages on this board. A malformed identifier is ignored\nrather than rejected, and every stage is returned.')
    term: str | None = Field(None, description='Case insensitive partial match against the stage name')
    page: int | None = Field(None, description='Page of results to return, starting at 1', ge=1)


class ListCounties(_Input):
    """List counties."""
    operation: Literal['list_counties'] = Field('list_counties', title='List counties', json_schema_extra={"ui:hidden": True})
    term: str | None = Field(None, description='Matches against the county *identifier*, not its display name. The term is\ndowncased and split on non word characters, and every resulting token must\nmatch the identifier.\n\nSo `harris` matches `harris_tx`, but `Harris County` matches nothing,\nbecause no county identifier contains `county`.')
    page: int | None = Field(None, description='Page of results to return, starting at 1', ge=1)


class ListTasks(_Input):
    """List tasks."""
    operation: Literal['list_tasks'] = Field('list_tasks', title='List tasks', json_schema_extra={"ui:hidden": True})
    term: str | None = Field(None, description='Case insensitive partial match against the task text')
    status: Literal['active', 'done', 'all'] | None = Field(None, description='Return only the tasks in this state. Defaults to `all`.')
    due_date: Literal['overdue', 'this_week', 'today', 'all_time'] | None = Field(None, description='Return only the tasks due in this window')
    membership_id: str | None = Field(None, description='Return only the tasks assigned to this member')
    unassigned: bool | None = Field(None, description='Return only the tasks with no member assigned')
    sort: Literal['due_date', 'deal_title'] | None = Field(None, description='Field to order the results by. Requires `dir` to be supplied as well.')
    dir: Literal['asc', 'desc'] | None = Field(None, description='Direction to apply `sort` in. Required whenever `sort` is supplied.')
    page: int | None = Field(None, description='Page of results to return, starting at 1', ge=1)


class ListTaskLists(_Input):
    """List task lists."""
    operation: Literal['list_task_lists'] = Field('list_task_lists', title='List task lists', json_schema_extra={"ui:hidden": True})
    deal_id: str | None = Field(None, description='Return only the task lists on this deal')
    term: str | None = Field(None, description='Case insensitive partial match against the task list name')
    page: int | None = Field(None, description='Page of results to return, starting at 1', ge=1)


class ListTags(_Input):
    """List tags."""
    operation: Literal['list_tags'] = Field('list_tags', title='List tags', json_schema_extra={"ui:hidden": True})
    context: Literal['property', 'contact'] | None = Field(None, description='Return only the tags that apply to this kind of record.')
    term: str | None = Field(None, description='Case insensitive partial match against the tag name')
    page: int | None = Field(None, description='Page of results to return, starting at 1', ge=1)


class CreateTask(_Input):
    """Create task."""
    operation: Literal['create_task'] = Field('create_task', title='Create task', json_schema_extra={"ui:hidden": True})
    due_date: date | None = Field(None, description='Date the task is due')
    membership_id: str | None = Field(None, description='Identifier of the member to assign the task to')
    task_list_id: str = Field(..., description='Identifier of the task list to add the task to', min_length=1)
    text: str = Field(..., description='Plain text body of the task')


class CompleteTask(_Input):
    """Complete task."""
    operation: Literal['complete_task'] = Field('complete_task', title='Complete task', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Identifier of the task to complete', min_length=1)


class UncompleteTask(_Input):
    """Uncomplete task."""
    operation: Literal['uncomplete_task'] = Field('uncomplete_task', title='Uncomplete task', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Identifier of the task to uncomplete', min_length=1)


class CreateTaskList(_Input):
    """Create task list."""
    operation: Literal['create_task_list'] = Field('create_task_list', title='Create task list', json_schema_extra={"ui:hidden": True})
    deal_id: str = Field(..., description='Identifier of the deal to add the task list to', min_length=1)
    name: str = Field(..., description='Display name of the task list')


class CreateTag(_Input):
    """Create tag."""
    operation: Literal['create_tag'] = Field('create_tag', title='Create tag', json_schema_extra={"ui:hidden": True})
    context: Literal['property', 'contact'] = Field(..., description='The kind of record the tag can be applied to')
    name: str = Field(..., description='Display name of the tag')
    variant: Literal['gray', 'green', 'azure', 'purple', 'pink', 'red', 'orange', 'yellow', 'iris', 'brown', 'mustard', 'teal'] | None = Field(None, description='Color the tag renders in. Defaults to `gray`.')


class TagContact(_Input):
    """Tag a contact."""
    operation: Literal['tag_contact'] = Field('tag_contact', title='Tag a contact', json_schema_extra={"ui:hidden": True})
    contact_id: str = Field(..., description='Identifier of the contact', min_length=1)
    tag_id: str = Field(..., description='Identifier of the tag', min_length=1)


class TagProperty(_Input):
    """Tag a property."""
    operation: Literal['tag_property'] = Field('tag_property', title='Tag a property', json_schema_extra={"ui:hidden": True})
    property_id: str = Field(..., description='Identifier of the property', min_length=1)
    tag_id: str = Field(..., description='Identifier of the tag', min_length=1)


class CreateRemark(_Input):
    """Create remark."""
    operation: Literal['create_remark'] = Field('create_remark', title='Create remark', json_schema_extra={"ui:hidden": True})
    deal_id: str = Field(..., description='Identifier of the deal to leave the remark on', min_length=1)
    text: str = Field(..., description='Plain text body of the remark')


class ListCampaigns(_Input):
    """List campaigns."""
    operation: Literal['list_campaigns'] = Field('list_campaigns', title='List campaigns', json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, description='Case insensitive partial match against the campaign name')
    sort: Literal['name', 'inserted_at', 'amount_spent', 'records_count', 'deals_count', 'offers_count', 'purchases_count', 'sales_count', 'response_rate'] | None = Field(None, description="Field to order the results by. Defaults to descending.\n\nAlongside the campaign's own fields, the results can be ordered by figures from\nits stats — `records_count`, `deals_count`, `offers_count`, `purchases_count`,\n`sales_count` and `response_rate` (deals per campaign).")
    dir: Literal['asc', 'desc'] | None = Field(None, description='Direction to apply `sort` in. Defaults to `desc`.')
    page: int | None = Field(None, description='Page of results to return, starting at 1', ge=1)


Operation = Annotated[Union[GetCurrentUser, ListContacts, CreateContact, UpdateContact, ListDeals, CreateDeal, UpdateDeal, ListProperties, CreateProperty, UpdateProperty, ListBoards, ListStages, ListCounties, ListTasks, ListTaskLists, ListTags, CreateTask, CompleteTask, UncompleteTask, CreateTaskList, CreateTag, TagContact, TagProperty, CreateRemark, ListCampaigns], Field(discriminator="operation")]


class REIPebbleConfig(NodeConfig[Operation, REIPebbleAPIKey]):
    pass


ROUTES = {'get_current_user': {'method': 'GET',
                      'path': '/api/user',
                      'query': [],
                      'path_fields': [],
                      'body_fields': []},
 'list_contacts': {'method': 'GET',
                   'path': '/api/contacts',
                   'query': ['name',
                             'has_phone',
                             'has_email',
                             'email',
                             'phone',
                             'category',
                             'tag_ids',
                             'do_not_mail',
                             'has_deal',
                             'deal_status',
                             'has_property',
                             'property_county_ids',
                             'campaign_id',
                             'campaign_record_code',
                             'sort',
                             'page'],
                   'path_fields': [],
                   'body_fields': []},
 'create_contact': {'method': 'POST',
                    'path': '/api/contacts',
                    'query': [],
                    'path_fields': [],
                    'body_fields': ['address',
                                    'category',
                                    'description',
                                    'do_not_mail',
                                    'email',
                                    'first_name',
                                    'last_name',
                                    'name',
                                    'phone',
                                    'phone_secondary']},
 'update_contact': {'method': 'PATCH',
                    'path': '/api/contacts/{id}',
                    'query': [],
                    'path_fields': ['id'],
                    'body_fields': ['address',
                                    'category',
                                    'description',
                                    'do_not_mail',
                                    'email',
                                    'first_name',
                                    'last_name',
                                    'name',
                                    'phone',
                                    'phone_secondary']},
 'list_deals': {'method': 'GET',
                'path': '/api/deals',
                'query': ['board_id',
                          'stage_id',
                          'term',
                          'status',
                          'priority',
                          'last_activity_after',
                          'last_activity_before',
                          'sort',
                          'dir',
                          'page'],
                'path_fields': [],
                'body_fields': []},
 'create_deal': {'method': 'POST',
                 'path': '/api/deals',
                 'query': [],
                 'path_fields': [],
                 'body_fields': ['board_id',
                                 'campaign_id',
                                 'contact_ids',
                                 'property_ids',
                                 'source',
                                 'stage_id',
                                 'status',
                                 'title',
                                 'value']},
 'update_deal': {'method': 'PATCH',
                 'path': '/api/deals/{id}',
                 'query': [],
                 'path_fields': ['id'],
                 'body_fields': ['board_id',
                                 'campaign_id',
                                 'contact_ids',
                                 'property_ids',
                                 'source',
                                 'stage_id',
                                 'status',
                                 'title',
                                 'value']},
 'list_properties': {'method': 'GET',
                     'path': '/api/properties',
                     'query': ['ids',
                               'county_ids',
                               'term',
                               'has_campaign',
                               'campaign_record_code',
                               'campaign_record_date_after',
                               'campaign_record_date_before',
                               'campaign_record_price_low',
                               'campaign_record_price_high',
                               'sort',
                               'dir',
                               'page'],
                     'path_fields': [],
                     'body_fields': []},
 'create_property': {'method': 'POST',
                     'path': '/api/properties',
                     'query': [],
                     'path_fields': [],
                     'body_fields': ['acreage',
                                     'address',
                                     'apn',
                                     'county_id',
                                     'geometry_collection',
                                     'legal_desc',
                                     'structure']},
 'update_property': {'method': 'PATCH',
                     'path': '/api/properties/{id}',
                     'query': [],
                     'path_fields': ['id'],
                     'body_fields': ['acreage',
                                     'address',
                                     'apn',
                                     'county_id',
                                     'geometry_collection',
                                     'legal_desc',
                                     'structure']},
 'list_boards': {'method': 'GET',
                 'path': '/api/boards',
                 'query': ['term', 'page'],
                 'path_fields': [],
                 'body_fields': []},
 'list_stages': {'method': 'GET',
                 'path': '/api/stages',
                 'query': ['board_id', 'term', 'page'],
                 'path_fields': [],
                 'body_fields': []},
 'list_counties': {'method': 'GET',
                   'path': '/api/counties',
                   'query': ['term', 'page'],
                   'path_fields': [],
                   'body_fields': []},
 'list_tasks': {'method': 'GET',
                'path': '/api/tasks',
                'query': ['term',
                          'status',
                          'due_date',
                          'membership_id',
                          'unassigned',
                          'sort',
                          'dir',
                          'page'],
                'path_fields': [],
                'body_fields': []},
 'list_task_lists': {'method': 'GET',
                     'path': '/api/task_lists',
                     'query': ['deal_id', 'term', 'page'],
                     'path_fields': [],
                     'body_fields': []},
 'list_tags': {'method': 'GET',
               'path': '/api/tags',
               'query': ['context', 'term', 'page'],
               'path_fields': [],
               'body_fields': []},
 'create_task': {'method': 'POST',
                 'path': '/api/tasks',
                 'query': [],
                 'path_fields': [],
                 'body_fields': ['due_date', 'membership_id', 'task_list_id', 'text']},
 'complete_task': {'method': 'POST',
                   'path': '/api/tasks/{id}/complete',
                   'query': [],
                   'path_fields': ['id'],
                   'body_fields': []},
 'uncomplete_task': {'method': 'POST',
                     'path': '/api/tasks/{id}/uncomplete',
                     'query': [],
                     'path_fields': ['id'],
                     'body_fields': []},
 'create_task_list': {'method': 'POST',
                      'path': '/api/task_lists',
                      'query': [],
                      'path_fields': [],
                      'body_fields': ['deal_id', 'name']},
 'create_tag': {'method': 'POST',
                'path': '/api/tags',
                'query': [],
                'path_fields': [],
                'body_fields': ['context', 'name', 'variant']},
 'tag_contact': {'method': 'POST',
                 'path': '/api/contacts/{contact_id}/tags',
                 'query': [],
                 'path_fields': ['contact_id'],
                 'body_fields': ['tag_id']},
 'tag_property': {'method': 'POST',
                  'path': '/api/properties/{property_id}/tags',
                  'query': [],
                  'path_fields': ['property_id'],
                  'body_fields': ['tag_id']},
 'create_remark': {'method': 'POST',
                   'path': '/api/remarks',
                   'query': [],
                   'path_fields': [],
                   'body_fields': ['deal_id', 'text']},
 'list_campaigns': {'method': 'GET',
                    'path': '/api/campaigns',
                    'query': ['name', 'sort', 'dir', 'page'],
                    'path_fields': [],
                    'body_fields': []}}


class REIPebbleNode(WorkflowNode):
    integration_type = "automation-rei-pebble"
    connection_evidence = ConnectionEvidence(noun="account", identity_operation="get_current_user", label_keys=("name", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return REIPebbleConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a REI Pebble API key")
        config = self.config.config
        route = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_unset=True)
        path = route["path"]
        for name in route["path_fields"]:
            path = path.replace("{" + name + "}", quote(str(getattr(config, name)), safe=""))
        params = {k: values[k] for k in route["query"] if values.get(k) is not None}
        # Pebble's docs require bracketed keys for multi-value array filters.
        params = {(k + "[]" if isinstance(v, list) else k): v for k, v in params.items()}
        body = {k: values[k] for k in route["body_fields"] if k in values and (values[k] is not None or k in {"due_date", "campaign_id", "value"})}
        # Optional nested address/structure fields are omitted when left blank.
        for name in ("address", "structure"):
            value = getattr(config, name, None)
            if isinstance(value, BaseModel) and name in body:
                body[name] = value.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        key = self.config.credentials.api_key
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(route["method"], BASE_URL + path,
                headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                params=params, **({"json": body} if route["body_fields"] else {}))
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection text for the connect verdict, removing any echoed key.
            raise ValueError(f"Pebble HTTP {response.status_code}: " + response.text.replace(key, "[redacted]")[:2000])
        try:
            result = response.json()
        except ValueError:
            raise ValueError("Pebble returned a non-JSON response") from None
        if not isinstance(result, dict):
            raise ValueError("Pebble returned an invalid response envelope")
        if route["method"] == "GET" and config.operation != "get_current_user":
            if not isinstance(result.get("entries"), list):
                raise ValueError("Pebble response is missing its entries list")
        elif not isinstance(result.get("data"), dict):
            raise ValueError("Pebble response is missing its data object")
        if config.operation == "get_current_user":
            if not all(isinstance(result["data"].get(k), str) and result["data"][k] for k in ("id", "name", "email")):
                raise ValueError("Pebble current-user response is missing its identity")
        if any(k in result for k in ("error", "errors")):
            raise ValueError("Pebble returned an error envelope")
        await self.emit(result)
        return result
