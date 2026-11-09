"""Responder V2.0 configs use the provider's published wire field names.

Each operation maps to one contract endpoint. Optional write fields are omitted
unless supplied; consent changes are separate, explicit operations.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _List(_Input):
    list_id: int = Field(..., gt=0, title="List ID")


class _Subscriber(_Input):
    subscriber_id: int = Field(..., gt=0, title="Subscriber ID")


class Notification(_Input):
    type_id: int
    email: str
    active: bool


class FieldOption(_Input):
    name: str
    is_default: Literal[0, 1] = 0


class UpdatedFieldOption(FieldOption):
    id: int | None = None


class _PersonalField(_Input):
    type_id: Literal[1, 2, 3, 4, 5, 6, 7, 8] = Field(..., description="1 short text, 2 long text, 3 date, 4 number, 5 phone, 6 single select, 7 multi select, 8 boolean.")
    name: str = Field(..., min_length=1)
    list_id: int | None = Field(None, gt=0, description="Omit for an account-wide field.")
    hidden: Literal[0, 1] | None = None
    position: int | None = None
    day: int | None = Field(None, ge=1, le=31)
    month: int | None = Field(None, ge=1, le=12)
    year: int | None = None
    default: str | None = None


class _Profile(_Input):
    first: str | None = None
    last: str | None = None
    email: str | None = None
    phone: str | None = None
    personal_fields: dict[str, Any] | None = Field(None, description="Personal field IDs mapped to values, including date objects.", json_schema_extra={"ui:widget": "code_editor"})
    tags_names: list[str] | None = Field(None, json_schema_extra={"ui:widget": "code_editor"})
    override: bool | None = None
    rejoin: bool | None = None
    unsubscribed: bool | None = Field(None, description="True deactivates email consent; false activates it.")


class GetAccount(_Input):
    operation: Literal["get_account"] = Field("get_account", title="Get Account", json_schema_extra={"ui:hidden": True})


class ListLists(_Input):
    operation: Literal["list_lists"] = Field("list_lists", title="List Lists", json_schema_extra={"ui:hidden": True})


class GetList(_List):
    operation: Literal["get_list"] = Field("get_list", title="Get List", json_schema_extra={"ui:hidden": True})


class CreateList(_Input):
    operation: Literal["create_list"] = Field("create_list", title="Create List", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    public_name: str | None = None
    sender_id: int | None = None
    is_dynamic: bool | None = None
    is_hidden: bool | None = None
    is_favorite: bool | None = None
    is_double_opt_in: bool | None = None
    notifications: Notification | None = None
    tags: list[int] | None = Field(None, description="List-type tag IDs (type_id 1).", json_schema_extra={"ui:widget": "code_editor"})


class ListListSubscribers(_List):
    operation: Literal["list_list_subscribers"] = Field("list_list_subscribers", title="List List Subscribers", json_schema_extra={"ui:hidden": True})


class GetSubscriber(_Input):
    operation: Literal["get_subscriber"] = Field("get_subscriber", title="Get Subscriber", json_schema_extra={"ui:hidden": True})
    identifier: str = Field(..., min_length=1, description="Subscriber ID or email address.")

    @field_validator("identifier")
    @classmethod
    def identifier_segment(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use a subscriber ID or email without control characters")
        return value


class CreateSubscriber(_Profile):
    operation: Literal["create_subscriber"] = Field("create_subscriber", title="Create Subscriber", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)
    name: str | None = None
    list_ids: list[int] = Field(..., min_length=1, description="Destination list IDs.", json_schema_extra={"ui:widget": "code_editor"})
    tags: list[int] | None = Field(None, json_schema_extra={"ui:widget": "code_editor"})
    disable_notification: bool | None = Field(None, description="True suppresses the list's new-subscriber notification.")

    @model_validator(mode="after")
    def unique_ids(self):
        for values in (self.list_ids, self.tags, self.tags_names):
            if values is not None and len(values) != len(set(values)):
                raise ValueError("List IDs and tags must be unique")
        return self


class UpdateSubscriber(_Profile, _Subscriber):
    operation: Literal["update_subscriber"] = Field("update_subscriber", title="Update Subscriber", json_schema_extra={"ui:hidden": True})
    join_date: date | None = None
    unsubscribed_phone: bool | None = None

    @model_validator(mode="after")
    def changes_required(self):
        if not any(getattr(self, key) is not None for key in self.model_fields_set - {"operation", "subscriber_id"}):
            raise ValueError("Supply at least one subscriber change")
        if self.tags_names is not None and len(self.tags_names) != len(set(self.tags_names)):
            raise ValueError("Tag names must be unique")
        return self


class DeleteSubscriber(_Subscriber):
    operation: Literal["delete_subscriber"] = Field("delete_subscriber", title="Delete Subscriber", json_schema_extra={"ui:hidden": True})


class SearchSubscribers(_Input):
    operation: Literal["search_subscribers"] = Field("search_subscribers", title="Search Subscribers", json_schema_extra={"ui:hidden": True})
    listId: int = Field(..., gt=0, title="List ID")
    searchKey: str = Field(..., min_length=1, title="Search Keyword")
    offset: int = Field(0, ge=0)
    size: int = Field(100, ge=1, description="Results per request; use offset for the next page.")


class RemoveListSubscriber(_List, _Subscriber):
    operation: Literal["remove_list_subscriber"] = Field("remove_list_subscriber", title="Remove List Subscriber", json_schema_extra={"ui:hidden": True})


class UpdateListSubscriber(_List, _Subscriber):
    operation: Literal["update_list_subscriber"] = Field("update_list_subscriber", title="Update List Subscriber", json_schema_extra={"ui:hidden": True})
    join_date: str | None = Field(None, description="YYYY-MM-DD HH:MM:SS")
    offset: int | None = None
    inactive: bool | None = None
    pending: bool | None = None
    list_seniority_date: str | None = Field(None, description="YYYY-MM-DD")

    @model_validator(mode="after")
    def changes_required(self):
        if not any(getattr(self, key) is not None for key in self.model_fields_set - {"operation", "list_id", "subscriber_id"}):
            raise ValueError("Supply at least one list membership change")
        return self


class UnsubscribeSubscriber(_Subscriber):
    operation: Literal["unsubscribe_subscriber"] = Field("unsubscribe_subscriber", title="Unsubscribe Subscriber", json_schema_extra={"ui:hidden": True})


class SubscribeSubscriber(_Subscriber):
    operation: Literal["subscribe_subscriber"] = Field("subscribe_subscriber", title="Subscribe Subscriber", json_schema_extra={"ui:hidden": True})


class ListPersonalFields(_Input):
    operation: Literal["list_personal_fields"] = Field("list_personal_fields", title="List Personal Fields", json_schema_extra={"ui:hidden": True})


class ListListPersonalFields(_List):
    operation: Literal["list_list_personal_fields"] = Field("list_list_personal_fields", title="List List Personal Fields", json_schema_extra={"ui:hidden": True})


class ListListFields(_List):
    operation: Literal["list_list_fields"] = Field("list_list_fields", title="List List Fields", json_schema_extra={"ui:hidden": True})


class CreatePersonalField(_PersonalField):
    operation: Literal["create_personal_field"] = Field("create_personal_field", title="Create Personal Field", json_schema_extra={"ui:hidden": True})
    options: list[FieldOption] | None = None


class UpdatePersonalField(_PersonalField):
    operation: Literal["update_personal_field"] = Field("update_personal_field", title="Update Personal Field", json_schema_extra={"ui:hidden": True})
    field_id: int = Field(..., gt=0)
    options: list[UpdatedFieldOption] | None = None


class ListTags(_Input):
    operation: Literal["list_tags"] = Field("list_tags", title="List Tags", json_schema_extra={"ui:hidden": True})


class ListSubscriberTags(_Input):
    operation: Literal["list_subscriber_tags"] = Field("list_subscriber_tags", title="List Subscriber Tags", json_schema_extra={"ui:hidden": True})


class GetSubscriberTag(_Input):
    operation: Literal["get_subscriber_tag"] = Field("get_subscriber_tag", title="Get Subscriber Tag", json_schema_extra={"ui:hidden": True})
    tag_id: int = Field(..., gt=0)


class CreateSubscriberTag(_Input):
    operation: Literal["create_subscriber_tag"] = Field("create_subscriber_tag", title="Create Subscriber Tag", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)


class RemoveSubscriberTag(_Subscriber):
    operation: Literal["remove_subscriber_tag"] = Field("remove_subscriber_tag", title="Remove Subscriber Tag", json_schema_extra={"ui:hidden": True})
    tag_id: int = Field(..., gt=0)


class AddUnwantedEmail(_Input):
    operation: Literal["add_unwanted_email"] = Field("add_unwanted_email", title="Add Unwanted Email", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1, description="Email to add to the account suppression list.")


Operation = Annotated[Union[GetAccount, ListLists, GetList, CreateList, ListListSubscribers, GetSubscriber, CreateSubscriber, UpdateSubscriber, DeleteSubscriber, SearchSubscribers, RemoveListSubscriber, UpdateListSubscriber, UnsubscribeSubscriber, SubscribeSubscriber, ListPersonalFields, ListListPersonalFields, ListListFields, CreatePersonalField, UpdatePersonalField, ListTags, ListSubscriberTags, GetSubscriberTag, CreateSubscriberTag, RemoveSubscriberTag, AddUnwantedEmail], Field(discriminator="operation")]

ROUTES = {'get_account': {'method': 'GET',
                 'path': '/me',
                 'path_fields': {},
                 'query_fields': [],
                 'body_fields': []},
 'list_lists': {'method': 'GET',
                'path': '/lists',
                'path_fields': {},
                'query_fields': [],
                'body_fields': []},
 'get_list': {'method': 'GET',
              'path': '/lists/{listid}',
              'path_fields': {'listid': 'list_id'},
              'query_fields': [],
              'body_fields': []},
 'create_list': {'method': 'POST',
                 'path': '/lists',
                 'path_fields': {},
                 'query_fields': [],
                 'body_fields': ['name',
                                 'public_name',
                                 'sender_id',
                                 'is_dynamic',
                                 'is_hidden',
                                 'is_favorite',
                                 'is_double_opt_in',
                                 'notifications',
                                 'tags']},
 'list_list_subscribers': {'method': 'GET',
                           'path': '/lists/{listid}/subscribers',
                           'path_fields': {'listid': 'list_id'},
                           'query_fields': [],
                           'body_fields': []},
 'get_subscriber': {'method': 'GET',
                    'path': '/subscribers/identifier/{identifier}',
                    'path_fields': {'identifier': 'identifier'},
                    'query_fields': [],
                    'body_fields': []},
 'create_subscriber': {'method': 'POST',
                       'path': '/subscribers',
                       'path_fields': {},
                       'query_fields': [],
                       'body_fields': ['first',
                                       'last',
                                       'email',
                                       'name',
                                       'list_ids',
                                       'personal_fields',
                                       'tags',
                                       'tags_names',
                                       'phone',
                                       'override',
                                       'rejoin',
                                       'unsubscribed',
                                       'disable_notification']},
 'update_subscriber': {'method': 'PUT',
                       'path': '/subscribers/{id}',
                       'path_fields': {'id': 'subscriber_id'},
                       'query_fields': [],
                       'body_fields': ['first',
                                       'last',
                                       'email',
                                       'personal_fields',
                                       'tags_names',
                                       'phone',
                                       'join_date',
                                       'override',
                                       'rejoin',
                                       'unsubscribed',
                                       'unsubscribed_phone']},
 'delete_subscriber': {'method': 'DELETE',
                       'path': '/subscribers/{id}',
                       'path_fields': {'id': 'subscriber_id'},
                       'query_fields': [],
                       'body_fields': []},
 'search_subscribers': {'method': 'POST',
                        'path': '/subscribers/search',
                        'path_fields': {},
                        'query_fields': ['listId', 'searchKey', 'offset', 'size'],
                        'body_fields': []},
 'remove_list_subscriber': {'method': 'DELETE',
                            'path': '/lists/{listid}/subscribers/{subscriberid}',
                            'path_fields': {'listid': 'list_id', 'subscriberid': 'subscriber_id'},
                            'query_fields': [],
                            'body_fields': []},
 'update_list_subscriber': {'method': 'PUT',
                            'path': '/lists/{listid}/subscribers/{subscriberid}',
                            'path_fields': {'listid': 'list_id', 'subscriberid': 'subscriber_id'},
                            'query_fields': [],
                            'body_fields': ['join_date',
                                            'offset',
                                            'inactive',
                                            'pending',
                                            'list_seniority_date']},
 'unsubscribe_subscriber': {'method': 'POST',
                            'path': '/req/unsubscribe',
                            'path_fields': {},
                            'query_fields': [],
                            'body_fields': ['subscriber_id']},
 'subscribe_subscriber': {'method': 'POST',
                          'path': '/req/subscribe',
                          'path_fields': {},
                          'query_fields': [],
                          'body_fields': ['subscriber_id']},
 'list_personal_fields': {'method': 'GET',
                          'path': '/personal-fields',
                          'path_fields': {},
                          'query_fields': [],
                          'body_fields': []},
 'list_list_personal_fields': {'method': 'GET',
                               'path': '/lists/{listid}/personal-fields',
                               'path_fields': {'listid': 'list_id'},
                               'query_fields': [],
                               'body_fields': []},
 'list_list_fields': {'method': 'GET',
                      'path': '/lists/{listid}/fields',
                      'path_fields': {'listid': 'list_id'},
                      'query_fields': [],
                      'body_fields': []},
 'create_personal_field': {'method': 'POST',
                           'path': '/personal-fields',
                           'path_fields': {},
                           'query_fields': [],
                           'body_fields': ['type_id',
                                           'name',
                                           'list_id',
                                           'hidden',
                                           'position',
                                           'day',
                                           'month',
                                           'year',
                                           'default',
                                           'options']},
 'update_personal_field': {'method': 'PUT',
                           'path': '/personal-fields/{id}',
                           'path_fields': {'id': 'field_id'},
                           'query_fields': [],
                           'body_fields': ['type_id',
                                           'name',
                                           'list_id',
                                           'hidden',
                                           'position',
                                           'day',
                                           'month',
                                           'year',
                                           'default',
                                           'options']},
 'list_tags': {'method': 'GET',
               'path': '/tag',
               'path_fields': {},
               'query_fields': [],
               'body_fields': []},
 'list_subscriber_tags': {'method': 'GET',
                          'path': '/tags/subscribers',
                          'path_fields': {},
                          'query_fields': [],
                          'body_fields': []},
 'get_subscriber_tag': {'method': 'GET',
                        'path': '/tags/subscribers/{id}',
                        'path_fields': {'id': 'tag_id'},
                        'query_fields': [],
                        'body_fields': []},
 'create_subscriber_tag': {'method': 'POST',
                           'path': '/tags/subscribers',
                           'path_fields': {},
                           'query_fields': [],
                           'body_fields': ['name']},
 'remove_subscriber_tag': {'method': 'DELETE',
                           'path': '/subscribers/{subscriberid}/tags/{tagid}',
                           'path_fields': {'subscriberid': 'subscriber_id', 'tagid': 'tag_id'},
                           'query_fields': [],
                           'body_fields': []},
 'add_unwanted_email': {'method': 'POST',
                        'path': '/emails/unwanted',
                        'path_fields': {},
                        'query_fields': [],
                        'body_fields': ['email']}}
