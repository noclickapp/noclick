"""Feathr API 0.0.0 operation models (https://docs.feathr.co/openapi.json)."""
from datetime import date, datetime
from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator


class FeathrInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def required_identifiers(self):
        values = self.model_dump()
        operation = values["operation"]
        if operation == "upsert_person" and not any(values.get(k) for k in ("email", "external_id", "f_id")):
            raise ValueError("Supply a person identifier")
        return self


class FeathrGetAccountConfig(FeathrInput):
    """Whoami. GET /me."""
    operation: Literal['get_account'] = Field('get_account', json_schema_extra={"ui:hidden": True})

class FeathrListCampaignsConfig(FeathrInput):
    """List Campaigns. GET /campaigns."""
    operation: Literal['list_campaigns'] = Field('list_campaigns', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description='1-based page number.')
    size: int = Field(25, ge=1, le=100, description='Items per page (max 100).')

class FeathrGetCampaignConfig(FeathrInput):
    """Get Campaign. GET /campaigns/{campaign_id}."""
    operation: Literal['get_campaign'] = Field('get_campaign', json_schema_extra={"ui:hidden": True})
    campaign_id: str = Field(..., min_length=1)

class FeathrListProjectsConfig(FeathrInput):
    """List Projects. GET /projects."""
    operation: Literal['list_projects'] = Field('list_projects', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description='1-based page number.')
    size: int = Field(25, ge=1, le=100, description='Items per page (max 100).')

class FeathrGetProjectConfig(FeathrInput):
    """Get Project. GET /projects/{project_id}."""
    operation: Literal['get_project'] = Field('get_project', json_schema_extra={"ui:hidden": True})
    project_id: str = Field(..., min_length=1)

class FeathrUpsertPersonConfig(FeathrInput):
    """Upsert Person. POST /persons."""
    operation: Literal['upsert_person'] = Field('upsert_person', json_schema_extra={"ui:hidden": True})
    mode: Literal['upsert', 'create', 'update'] = Field('upsert', description='upsert (default) matches-or-creates; create returns 409 if the person already exists; update returns 404 if it does not.')
    lists: Literal['replace', 'merge'] = Field('replace', description='replace (default) overwrites the stored `emails` and `companies` with the sent lists; merge adds the sent values to them and removes none.')
    external_id: str | None = Field(None, min_length=1)
    email: str | None = Field(None)
    f_id: str | None = Field(None, min_length=1)
    first_name: str | None = Field(None)
    last_name: str | None = Field(None)
    name: str | None = Field(None)
    phone: str | None = Field(None)
    language: str | None = Field(None)
    ethnicity: str | None = Field(None)
    edu: str | None = Field(None)
    occupation: str | None = Field(None)
    pseudonym: str | None = Field(None)
    companies: list[str] | None = Field(None)
    emails: list[str] | None = Field(None, max_length=50, description='Additional email addresses. Each is normalized as `email` is; a blank or malformed address, a repeat, or the primary `email` is dropped. Replaces the stored list, unless the write sets `lists=merge`.')
    tags: list[str] | None = Field(None)
    email_opt_out: bool | None = Field(None)
    income: int | None = Field(None)
    age: int | None = Field(None)
    date_of_birth: date | None = Field(None, description='Date of birth, as YYYY-MM-DD. Not in the future.')
    address_country_name: str | None = Field(None)
    address_administrative_area_name: str | None = Field(None)
    address_locality: str | None = Field(None)
    address_premise1: str | None = Field(None)
    address_premise2: str | None = Field(None)
    address_postal_code: str | None = Field(None)
    custom_fields: dict[str, Any] | None = Field(None)

class FeathrGetPersonConfig(FeathrInput):
    """Get Person. GET /persons/{person_id}."""
    operation: Literal['get_person'] = Field('get_person', json_schema_extra={"ui:hidden": True})
    person_id: str = Field(..., min_length=1)
    extended: bool = Field(False, description='Include the full field set (name, language, pseudonym, occupation, companies, emails, address, age, ethnicity, income, edu, tags, email_opt_out, is_archived, person_url). Off by default.')

class FeathrUpdatePersonConfig(FeathrInput):
    """Update Person. PATCH /persons/{person_id}."""
    operation: Literal['update_person'] = Field('update_person', json_schema_extra={"ui:hidden": True})
    person_id: str = Field(..., min_length=1)
    email: str | None = Field(None)
    first_name: str | None = Field(None)
    last_name: str | None = Field(None)
    phone: str | None = Field(None)
    custom_fields: dict[str, Any] | None = Field(None)

class FeathrDeletePersonConfig(FeathrInput):
    """Delete Person. DELETE /persons/{person_id}."""
    operation: Literal['delete_person'] = Field('delete_person', json_schema_extra={"ui:hidden": True})
    person_id: str = Field(..., min_length=1)

class FeathrAddPersonTagsConfig(FeathrInput):
    """Add Person Tags. POST /persons/{person_id}/tags."""
    operation: Literal['add_person_tags'] = Field('add_person_tags', json_schema_extra={"ui:hidden": True})
    person_id: str = Field(..., min_length=1)
    tag_ids: list[str] = Field(..., min_length=1)

class FeathrRemovePersonTagConfig(FeathrInput):
    """Remove Person Tag. DELETE /persons/{person_id}/tags/{tag_id}."""
    operation: Literal['remove_person_tag'] = Field('remove_person_tag', json_schema_extra={"ui:hidden": True})
    person_id: str = Field(..., min_length=1)
    tag_id: str = Field(..., min_length=1)

class FeathrCreateTagConfig(FeathrInput):
    """Create Tag. POST /tags."""
    operation: Literal['create_tag'] = Field('create_tag', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=64)
    context: Literal['event', 'account', 'person_segment', 'partner', 'breadcrumb', 'person'] = Field(...)

class FeathrGetTagConfig(FeathrInput):
    """Get Tag. GET /tags/{tag_id}."""
    operation: Literal['get_tag'] = Field('get_tag', json_schema_extra={"ui:hidden": True})
    tag_id: str = Field(..., min_length=1)

class FeathrUpdateTagConfig(FeathrInput):
    """Update Tag. PATCH /tags/{tag_id}."""
    operation: Literal['update_tag'] = Field('update_tag', json_schema_extra={"ui:hidden": True})
    tag_id: str = Field(..., min_length=1)
    name: str | None = Field(None, min_length=1, max_length=64)
    context: Literal['event', 'account', 'person_segment', 'partner', 'breadcrumb', 'person'] | None = Field(None)

class FeathrDeleteTagConfig(FeathrInput):
    """Delete Tag. DELETE /tags/{tag_id}."""
    operation: Literal['delete_tag'] = Field('delete_tag', json_schema_extra={"ui:hidden": True})
    tag_id: str = Field(..., min_length=1)

class FeathrCreateCustomFieldConfig(FeathrInput):
    """Create Custom Field. POST /custom-fields."""
    operation: Literal['create_custom_field'] = Field('create_custom_field', json_schema_extra={"ui:hidden": True})
    key: str = Field(..., min_length=1, max_length=255)
    collection: Literal['Person', 'Breadcrumb', 'Partner'] = Field(...)
    data_type: Literal['str', 'int', 'float', 'bool', 'list', 'date', 'money', 'unicode'] = Field(...)
    form_type: Literal['text', 'number', 'textarea', 'email', 'url', 'image'] = Field('text')
    label: str | None = Field(None, max_length=255)
    description: str | None = Field(None)

class FeathrGetCustomFieldConfig(FeathrInput):
    """Get Custom Field. GET /custom-fields/{field_id}."""
    operation: Literal['get_custom_field'] = Field('get_custom_field', json_schema_extra={"ui:hidden": True})
    field_id: str = Field(..., min_length=1)

class FeathrUpdateCustomFieldConfig(FeathrInput):
    """Update Custom Field. PATCH /custom-fields/{field_id}."""
    operation: Literal['update_custom_field'] = Field('update_custom_field', json_schema_extra={"ui:hidden": True})
    field_id: str = Field(..., min_length=1)
    label: str | None = Field(None, max_length=255)
    description: str | None = Field(None)
    form_type: Literal['text', 'number', 'textarea', 'email', 'url', 'image'] | None = Field(None)

class FeathrDeleteCustomFieldConfig(FeathrInput):
    """Delete Custom Field. DELETE /custom-fields/{field_id}."""
    operation: Literal['delete_custom_field'] = Field('delete_custom_field', json_schema_extra={"ui:hidden": True})
    field_id: str = Field(..., min_length=1)


FeathrOperation = Annotated[Union[FeathrGetAccountConfig, FeathrListCampaignsConfig, FeathrGetCampaignConfig, FeathrListProjectsConfig, FeathrGetProjectConfig, FeathrUpsertPersonConfig, FeathrGetPersonConfig, FeathrUpdatePersonConfig, FeathrDeletePersonConfig, FeathrAddPersonTagsConfig, FeathrRemovePersonTagConfig, FeathrCreateTagConfig, FeathrGetTagConfig, FeathrUpdateTagConfig, FeathrDeleteTagConfig, FeathrCreateCustomFieldConfig, FeathrGetCustomFieldConfig, FeathrUpdateCustomFieldConfig, FeathrDeleteCustomFieldConfig], Field(discriminator="operation")]

OPERATIONS = {'get_account': {'method': 'GET',
                 'path': '/me',
                 'path_fields': [],
                 'query': {},
                 'headers': {},
                 'body': [],
                 'status': 200},
 'list_campaigns': {'method': 'GET',
                    'path': '/campaigns',
                    'path_fields': [],
                    'query': {'page': 'page', 'size': 'size'},
                    'headers': {},
                    'body': [],
                    'status': 200},
 'get_campaign': {'method': 'GET',
                  'path': '/campaigns/{campaign_id}',
                  'path_fields': ['campaign_id'],
                  'query': {},
                  'headers': {},
                  'body': [],
                  'status': 200},
 'list_projects': {'method': 'GET',
                   'path': '/projects',
                   'path_fields': [],
                   'query': {'page': 'page', 'size': 'size'},
                   'headers': {},
                   'body': [],
                   'status': 200},
 'get_project': {'method': 'GET',
                 'path': '/projects/{project_id}',
                 'path_fields': ['project_id'],
                 'query': {},
                 'headers': {},
                 'body': [],
                 'status': 200},
 'upsert_person': {'method': 'POST',
                   'path': '/persons',
                   'path_fields': [],
                   'query': {'mode': 'mode', 'lists': 'lists'},
                   'headers': {},
                   'body': ['external_id',
                            'email',
                            'f_id',
                            'first_name',
                            'last_name',
                            'name',
                            'phone',
                            'language',
                            'ethnicity',
                            'edu',
                            'occupation',
                            'pseudonym',
                            'companies',
                            'emails',
                            'tags',
                            'email_opt_out',
                            'income',
                            'age',
                            'date_of_birth',
                            'address_country_name',
                            'address_administrative_area_name',
                            'address_locality',
                            'address_premise1',
                            'address_premise2',
                            'address_postal_code',
                            'custom_fields'],
                   'status': 200},
 'get_person': {'method': 'GET',
                'path': '/persons/{person_id}',
                'path_fields': ['person_id'],
                'query': {'extended': 'extended'},
                'headers': {},
                'body': [],
                'status': 200},
 'update_person': {'method': 'PATCH',
                   'path': '/persons/{person_id}',
                   'path_fields': ['person_id'],
                   'query': {},
                   'headers': {},
                   'body': ['email', 'first_name', 'last_name', 'phone', 'custom_fields'],
                   'status': 200},
 'delete_person': {'method': 'DELETE',
                   'path': '/persons/{person_id}',
                   'path_fields': ['person_id'],
                   'query': {},
                   'headers': {},
                   'body': [],
                   'status': 204},
 'add_person_tags': {'method': 'POST',
                     'path': '/persons/{person_id}/tags',
                     'path_fields': ['person_id'],
                     'query': {},
                     'headers': {},
                     'body': ['tag_ids'],
                     'status': 204},
 'remove_person_tag': {'method': 'DELETE',
                       'path': '/persons/{person_id}/tags/{tag_id}',
                       'path_fields': ['person_id', 'tag_id'],
                       'query': {},
                       'headers': {},
                       'body': [],
                       'status': 204},
 'create_tag': {'method': 'POST',
                'path': '/tags',
                'path_fields': [],
                'query': {},
                'headers': {},
                'body': ['name', 'context'],
                'status': 201},
 'get_tag': {'method': 'GET',
             'path': '/tags/{tag_id}',
             'path_fields': ['tag_id'],
             'query': {},
             'headers': {},
             'body': [],
             'status': 200},
 'update_tag': {'method': 'PATCH',
                'path': '/tags/{tag_id}',
                'path_fields': ['tag_id'],
                'query': {},
                'headers': {},
                'body': ['name', 'context'],
                'status': 200},
 'delete_tag': {'method': 'DELETE',
                'path': '/tags/{tag_id}',
                'path_fields': ['tag_id'],
                'query': {},
                'headers': {},
                'body': [],
                'status': 204},
 'create_custom_field': {'method': 'POST',
                         'path': '/custom-fields',
                         'path_fields': [],
                         'query': {},
                         'headers': {},
                         'body': ['key', 'collection', 'data_type', 'form_type', 'label', 'description'],
                         'status': 201},
 'get_custom_field': {'method': 'GET',
                      'path': '/custom-fields/{field_id}',
                      'path_fields': ['field_id'],
                      'query': {},
                      'headers': {},
                      'body': [],
                      'status': 200},
 'update_custom_field': {'method': 'PATCH',
                         'path': '/custom-fields/{field_id}',
                         'path_fields': ['field_id'],
                         'query': {},
                         'headers': {},
                         'body': ['label', 'description', 'form_type'],
                         'status': 200},
 'delete_custom_field': {'method': 'DELETE',
                         'path': '/custom-fields/{field_id}',
                         'path_fields': ['field_id'],
                         'query': {},
                         'headers': {},
                         'body': [],
                         'status': 204}}
