"""Pipeless app events, activity feeds and recommendations (published API v1).

Each operation sends one request to api.pipeless.io. The provider specifies JSON
bodies on GET as well as write requests. A 202 means accepted, not completed.
Auth example: https://docs.pipeless.io/docs/uploading-data
"""
from __future__ import annotations
import json
import re
from typing import Annotated, Literal, Optional, Union
import httpx
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
)
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes import pipeless_operations as models
from utils.ssrf import guarded_async_client


class PipelessAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Pipeless API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://pipeless.io/apps",
            "x-credential-instructions": "Open Account → Apps in Pipeless and copy your App ID and app API key. Paste the key without the Bearer prefix. Each app has its own key and graph database. NoClick checks the connection by reading recent events for that app.",
        },
    )
    credential_type: Literal["pipeless_api_key"] = Field(
        "pipeless_api_key", json_schema_extra={"ui:hidden": True}
    )
    app_id: str = Field(..., title="App ID", min_length=1, max_length=40)
    api_key: str = Field(
        ...,
        title="API key",
        min_length=1,
        max_length=4096,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("app_id", mode="before")
    @classmethod
    def app(cls, value):
        if not isinstance(value, str) or not re.fullmatch(
            r"[1-9][0-9]{0,39}", value.strip()
        ):
            raise ValueError("Paste the numeric App ID from your Pipeless Apps page")
        return value.strip()

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a prefix or whitespace")
        return value


class _Input(BaseModel):
    # Saved workflow metadata can accompany operation fields; only BODY_FIELDS
    # is sent to Pipeless. Nested API objects remain strict.
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


def _json_input(value, annotation):
    try:
        raw = json.loads(value) if isinstance(value, str) else value
        adapter = TypeAdapter(annotation)
        parsed = adapter.validate_python(raw)
        return adapter.dump_json(parsed, exclude_none=True).decode()
    except (ValueError, TypeError):
        raise ValueError(
            "Enter JSON matching the documented Pipeless field structure"
        ) from None


class PipelessCreateEventConfig(_Input):
    "Create a single event."
    operation: Literal["create_event"] = Field(
        "create_event", json_schema_extra={"ui:hidden": True}
    )
    event: Annotated[
        str, BeforeValidator(lambda value: _json_input(value, models.CreateEventEvent))
    ] = Field(
        ...,
        title="Event",
        description="The event to be added.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "type": "object",
                "default": {
                    "start_object": {
                        "id": "Tim",
                        "type": "user",
                        "created_on": "2020-09-20T21:57:06",
                    },
                    "relationship": {
                        "type": "interestedIn",
                        "created_on": "2020-09-28T09:31:18",
                    },
                    "end_object": {
                        "id": "photography",
                        "type": "skill",
                        "created_on": "2020-06-03T15:40:22",
                    },
                },
                "description": "The event to be added.",
                "required": ["start_object", "relationship", "end_object"],
                "properties": {
                    "start_object": {
                        "title": "",
                        "type": "object",
                        "description": "An object to be written to your data. Only one object can exist for each type + id combo. If any of your write patterns provide an object that doesn't exist, it will be created. If the object already exists, the existing object will be used in your write operation, and if created_on or modified_on differ from the values already associated with the object, those values will be updated.",
                        "properties": {
                            "id": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 40,
                                "description": "The id of your object. The id can be a string (up to 40 characters) containing any number, alpha character, spaces, or the following special characters: @-!#%^&()/+=;:'\"?<>\\][{}.,",
                            },
                            "type": {
                                "type": "string",
                                "title": "",
                                "enum": [
                                    "user",
                                    "product",
                                    "image",
                                    "comment",
                                    "article",
                                    "post",
                                    "video",
                                    "content",
                                    "tag",
                                    "category",
                                    "app",
                                    "book",
                                    "person",
                                    "skill",
                                    "job",
                                    "company",
                                    "account",
                                    "card",
                                    "country",
                                    "state",
                                    "film",
                                    "cart",
                                    "document",
                                    "project",
                                ],
                                "description": "The type of an object. Can be any one of our predefined types. Although it is flexible what object type you use, as a best practice, we suggest you pick the one that relates best to the data you are representing. Doing this also allows specific algos to automatically work with their default settings.",
                                "x-examples": {},
                            },
                            "created_on": {
                                "type": "string",
                                "format": "date-time",
                                "description": "An optional DateTime string in the format YYYY-MM-DDTHH:MM:SS in whatever timezone you use. If not set, and the object needs to be created, this value will be set to the current UTC time.",
                            },
                            "modified_on": {
                                "type": "string",
                                "format": "date-time",
                                "description": "An optional DateTime string in the format YYYY-MM-DDTHH:MM:SS in whatever timezone you use. If not set, the value will be set to the same value as created_on.",
                            },
                        },
                        "required": ["id", "type"],
                        "x-examples": {},
                    },
                    "relationship": {
                        "title": "",
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": [
                                    "posted",
                                    "followed",
                                    "liked",
                                    "favorited",
                                    "saved",
                                    "unsaved",
                                    "disliked",
                                    "purchased",
                                    "commentedOn",
                                    "created",
                                    "viewed",
                                    "reported",
                                    "blocked",
                                    "deleted",
                                    "authored",
                                    "used",
                                    "dismissed",
                                    "loggedIn",
                                    "taggedWith",
                                    "categorizedIn",
                                    "interestedIn",
                                    "locatedIn",
                                    "readQuarter",
                                    "readHalf",
                                    "readAll",
                                    "subscribedTo",
                                    "subscribedFrom",
                                    "addedTo",
                                    "madeBy",
                                    "pausedOn",
                                    "updated",
                                    "enabled",
                                    "disabled",
                                ],
                                "title": "",
                                "description": "The type of relationship for an event. Can be any one of our predefined types. Although it is flexible what relationship type you use, as a best practice, we suggest you pick the one that relates best to the data you are representing. Doing this also allows specific algos to automatically work with their default settings.",
                            },
                            "created_on": {
                                "type": "string",
                                "format": "date-time",
                                "description": "An optional DateTime string in the format YYYY-MM-DDTHH:MM:SS in whatever timezone you use. If not set, and the relationship needs to be created, this value will be set to the current UTC time.",
                            },
                            "single": {
                                "title": "",
                                "type": "boolean",
                                "description": "Whether the relationship can be duplicated or not. If single is true (default), then a relationship of each type can only exist once between the same start and end objects. If false, a relationship of the same type can exist multiple times between the same start and end objects.",
                            },
                        },
                        "required": ["type"],
                        "description": "The relationship for your event.",
                    },
                    "end_object": {
                        "title": "",
                        "type": "object",
                        "description": "An object to be written to your data. Only one object can exist for each type + id combo. If any of your write patterns provide an object that doesn't exist, it will be created. If the object already exists, the existing object will be used in your write operation, and if created_on or modified_on differ from the values already associated with the object, those values will be updated.",
                        "properties": {
                            "id": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 40,
                                "description": "The id of your object. The id can be a string (up to 40 characters) containing any number, alpha character, spaces, or the following special characters: @-!#%^&()/+=;:'\"?<>\\][{}.,",
                            },
                            "type": {
                                "type": "string",
                                "title": "",
                                "enum": [
                                    "user",
                                    "product",
                                    "image",
                                    "comment",
                                    "article",
                                    "post",
                                    "video",
                                    "content",
                                    "tag",
                                    "category",
                                    "app",
                                    "book",
                                    "person",
                                    "skill",
                                    "job",
                                    "company",
                                    "account",
                                    "card",
                                    "country",
                                    "state",
                                    "film",
                                    "cart",
                                    "document",
                                    "project",
                                ],
                                "description": "The type of an object. Can be any one of our predefined types. Although it is flexible what object type you use, as a best practice, we suggest you pick the one that relates best to the data you are representing. Doing this also allows specific algos to automatically work with their default settings.",
                                "x-examples": {},
                            },
                            "created_on": {
                                "type": "string",
                                "format": "date-time",
                                "description": "An optional DateTime string in the format YYYY-MM-DDTHH:MM:SS in whatever timezone you use. If not set, and the object needs to be created, this value will be set to the current UTC time.",
                            },
                            "modified_on": {
                                "type": "string",
                                "format": "date-time",
                                "description": "An optional DateTime string in the format YYYY-MM-DDTHH:MM:SS in whatever timezone you use. If not set, the value will be set to the same value as created_on.",
                            },
                        },
                        "required": ["id", "type"],
                        "x-examples": {},
                    },
                },
            },
        },
    )
    synchronous: Optional[bool] = Field(
        None,
        title="Synchronous",
        description="Whether the event should be created asynchronously or synchronously. Default is false (asynchronous). On success, async will return 202 Accepted, sync will return 201 Created.",
    )


class PipelessDeleteEventConfig(_Input):
    "Delete one or more events."
    operation: Literal["delete_event"] = Field(
        "delete_event", json_schema_extra={"ui:hidden": True}
    )
    event: Annotated[
        str, BeforeValidator(lambda value: _json_input(value, models.DeleteEventEvent))
    ] = Field(
        ...,
        title="Event",
        description="Details to specify which event(s) should be deleted. Only events that match all 3 event parts (start, relationship, end) will be deleted.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "description": "Details to specify which event(s) should be deleted. Only events that match all 3 event parts (start, relationship, end) will be deleted.",
                "type": "object",
                "required": ["start_object", "relationship", "end_object"],
                "properties": {
                    "start_object": {
                        "title": "",
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "title": "",
                                "minLength": 1,
                                "maxLength": 40,
                                "description": "id of the object you want to fetch.",
                            },
                            "type": {
                                "type": "string",
                                "title": "",
                                "enum": [
                                    "user",
                                    "product",
                                    "image",
                                    "comment",
                                    "article",
                                    "post",
                                    "video",
                                    "content",
                                    "tag",
                                    "category",
                                    "app",
                                    "book",
                                    "person",
                                    "skill",
                                    "job",
                                    "company",
                                    "account",
                                    "card",
                                    "country",
                                    "state",
                                    "film",
                                    "cart",
                                    "document",
                                    "project",
                                ],
                                "description": "type of the object you want to fetch.",
                                "x-examples": {},
                            },
                        },
                        "required": ["id", "type"],
                    },
                    "relationship": {
                        "type": "object",
                        "description": "When specifying the relationship of the event(s) to delete, if you only specify a type, then all events starting at the start object and going to the end object of the specified type will be deleted. If a created_on datetime is specified too, then only events where the relationship matches the specified type and created_on will be deleted.",
                        "required": ["type"],
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": [
                                    "posted",
                                    "followed",
                                    "liked",
                                    "favorited",
                                    "saved",
                                    "unsaved",
                                    "disliked",
                                    "purchased",
                                    "commentedOn",
                                    "created",
                                    "viewed",
                                    "reported",
                                    "blocked",
                                    "deleted",
                                    "authored",
                                    "used",
                                    "dismissed",
                                    "loggedIn",
                                    "taggedWith",
                                    "categorizedIn",
                                    "interestedIn",
                                    "locatedIn",
                                    "readQuarter",
                                    "readHalf",
                                    "readAll",
                                    "subscribedTo",
                                    "subscribedFrom",
                                    "addedTo",
                                    "madeBy",
                                    "pausedOn",
                                    "updated",
                                    "enabled",
                                    "disabled",
                                ],
                            },
                            "created_on": {"type": "string", "format": "date-time"},
                        },
                    },
                    "end_object": {
                        "title": "",
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "title": "",
                                "minLength": 1,
                                "maxLength": 40,
                                "description": "id of the object you want to delete",
                            },
                            "type": {
                                "type": "string",
                                "title": "",
                                "enum": [
                                    "user",
                                    "product",
                                    "image",
                                    "comment",
                                    "article",
                                    "post",
                                    "video",
                                    "content",
                                    "tag",
                                    "category",
                                    "app",
                                    "book",
                                    "person",
                                    "skill",
                                    "job",
                                    "company",
                                    "account",
                                    "card",
                                    "country",
                                    "state",
                                    "film",
                                    "cart",
                                    "document",
                                    "project",
                                ],
                                "description": "type of the object you want to fetch.",
                                "x-examples": {},
                            },
                            "all": {
                                "type": "boolean",
                                "description": "If you want to delete all the relationships from the start object to the specified end object type (of any id), set this value to true. If true, the end object of the event will match any object of the specified type. Default value is false, meaning a specific id is required.",
                            },
                        },
                        "required": ["type"],
                    },
                },
            },
        },
    )


class PipelessCreateEventsBatchConfig(_Input):
    "Create up to 10 events in one API call."
    operation: Literal["create_events_batch"] = Field(
        "create_events_batch", json_schema_extra={"ui:hidden": True}
    )
    events: Annotated[
        str,
        BeforeValidator(
            lambda value: _json_input(value, list[models.CreateEventsBatchEventsItem])
        ),
    ] = Field(
        ...,
        title="Events",
        description="The events to be added.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "type": "array",
                "description": "The events to be added.",
                "items": {
                    "type": "object",
                    "description": "An individual event.",
                    "properties": {
                        "start_object": {
                            "title": "",
                            "type": "object",
                            "description": "An object to be written to your data. Only one object can exist for each type + id combo. If any of your write patterns provide an object that doesn't exist, it will be created. If the object already exists, the existing object will be used in your write operation, and if created_on or modified_on differ from the values already associated with the object, those values will be updated.",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 40,
                                    "description": "The id of your object. The id can be a string (up to 40 characters) containing any number, alpha character, spaces, or the following special characters: @-!#%^&()/+=;:'\"?<>\\][{}.,",
                                },
                                "type": {
                                    "type": "string",
                                    "title": "",
                                    "enum": [
                                        "user",
                                        "product",
                                        "image",
                                        "comment",
                                        "article",
                                        "post",
                                        "video",
                                        "content",
                                        "tag",
                                        "category",
                                        "app",
                                        "book",
                                        "person",
                                        "skill",
                                        "job",
                                        "company",
                                        "account",
                                        "card",
                                        "country",
                                        "state",
                                        "film",
                                        "cart",
                                        "document",
                                        "project",
                                    ],
                                    "description": "The type of an object. Can be any one of our predefined types. Although it is flexible what object type you use, as a best practice, we suggest you pick the one that relates best to the data you are representing. Doing this also allows specific algos to automatically work with their default settings.",
                                    "x-examples": {},
                                },
                                "created_on": {
                                    "type": "string",
                                    "format": "date-time",
                                    "description": "An optional DateTime string in the format YYYY-MM-DDTHH:MM:SS in whatever timezone you use. If not set, and the object needs to be created, this value will be set to the current UTC time.",
                                },
                                "modified_on": {
                                    "type": "string",
                                    "format": "date-time",
                                    "description": "An optional DateTime string in the format YYYY-MM-DDTHH:MM:SS in whatever timezone you use. If not set, the value will be set to the same value as created_on.",
                                },
                            },
                            "required": ["id", "type"],
                            "x-examples": {},
                        },
                        "relationship": {
                            "title": "",
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": [
                                        "posted",
                                        "followed",
                                        "liked",
                                        "favorited",
                                        "saved",
                                        "unsaved",
                                        "disliked",
                                        "purchased",
                                        "commentedOn",
                                        "created",
                                        "viewed",
                                        "reported",
                                        "blocked",
                                        "deleted",
                                        "authored",
                                        "used",
                                        "dismissed",
                                        "loggedIn",
                                        "taggedWith",
                                        "categorizedIn",
                                        "interestedIn",
                                        "locatedIn",
                                        "readQuarter",
                                        "readHalf",
                                        "readAll",
                                        "subscribedTo",
                                        "subscribedFrom",
                                        "addedTo",
                                        "madeBy",
                                        "pausedOn",
                                        "updated",
                                        "enabled",
                                        "disabled",
                                    ],
                                    "title": "",
                                    "description": "The type of relationship for an event. Can be any one of our predefined types. Although it is flexible what relationship type you use, as a best practice, we suggest you pick the one that relates best to the data you are representing. Doing this also allows specific algos to automatically work with their default settings.",
                                },
                                "created_on": {
                                    "type": "string",
                                    "format": "date-time",
                                    "description": "An optional DateTime string in the format YYYY-MM-DDTHH:MM:SS in whatever timezone you use. If not set, and the relationship needs to be created, this value will be set to the current UTC time.",
                                },
                                "single": {
                                    "title": "",
                                    "type": "boolean",
                                    "description": "Whether the relationship can be duplicated or not. If single is true (default), then a relationship of each type can only exist once between the same start and end objects. If false, a relationship of the same type can exist multiple times between the same start and end objects.",
                                },
                            },
                            "required": ["type"],
                        },
                        "end_object": {
                            "title": "",
                            "type": "object",
                            "description": "An object to be written to your data. Only one object can exist for each type + id combo. If any of your write patterns provide an object that doesn't exist, it will be created. If the object already exists, the existing object will be used in your write operation, and if created_on or modified_on differ from the values already associated with the object, those values will be updated.",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 40,
                                    "description": "The id of your object. The id can be a string (up to 40 characters) containing any number, alpha character, spaces, or the following special characters: @-!#%^&()/+=;:'\"?<>\\][{}.,",
                                },
                                "type": {
                                    "type": "string",
                                    "title": "",
                                    "enum": [
                                        "user",
                                        "product",
                                        "image",
                                        "comment",
                                        "article",
                                        "post",
                                        "video",
                                        "content",
                                        "tag",
                                        "category",
                                        "app",
                                        "book",
                                        "person",
                                        "skill",
                                        "job",
                                        "company",
                                        "account",
                                        "card",
                                        "country",
                                        "state",
                                        "film",
                                        "cart",
                                        "document",
                                        "project",
                                    ],
                                    "description": "The type of an object. Can be any one of our predefined types. Although it is flexible what object type you use, as a best practice, we suggest you pick the one that relates best to the data you are representing. Doing this also allows specific algos to automatically work with their default settings.",
                                    "x-examples": {},
                                },
                                "created_on": {
                                    "type": "string",
                                    "format": "date-time",
                                    "description": "An optional DateTime string in the format YYYY-MM-DDTHH:MM:SS in whatever timezone you use. If not set, and the object needs to be created, this value will be set to the current UTC time.",
                                },
                                "modified_on": {
                                    "type": "string",
                                    "format": "date-time",
                                    "description": "An optional DateTime string in the format YYYY-MM-DDTHH:MM:SS in whatever timezone you use. If not set, the value will be set to the same value as created_on.",
                                },
                            },
                            "required": ["id", "type"],
                            "x-examples": {},
                        },
                    },
                    "required": ["start_object", "relationship", "end_object"],
                },
            },
        },
    )
    synchronous: Optional[bool] = Field(
        None,
        title="Synchronous",
        description="Whether the events should be created asynchronously or synchronously. Default is false (asynchronous)",
    )


class PipelessGetObjectConfig(_Input):
    "Get basic info on a single object."
    operation: Literal["get_object"] = Field(
        "get_object", json_schema_extra={"ui:hidden": True}
    )
    object: Annotated[
        str, BeforeValidator(lambda value: _json_input(value, models.ObjectLookup))
    ] = Field(
        ...,
        title="Object",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "title": "",
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "title": "",
                        "minLength": 1,
                        "maxLength": 40,
                        "description": "id of the object you want to fetch.",
                    },
                    "type": {
                        "type": "string",
                        "title": "",
                        "enum": [
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ],
                        "description": "type of the object you want to fetch.",
                        "x-examples": {},
                    },
                },
                "required": ["id", "type"],
            },
        },
    )


class PipelessDeleteObjectConfig(_Input):
    "Delete a single object and all the relationships/events it's connected to."
    operation: Literal["delete_object"] = Field(
        "delete_object", json_schema_extra={"ui:hidden": True}
    )
    object: Annotated[
        str, BeforeValidator(lambda value: _json_input(value, models.ObjectLookup))
    ] = Field(
        ...,
        title="Object",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "title": "",
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "title": "",
                        "minLength": 1,
                        "maxLength": 40,
                        "description": "id of the object you want to fetch.",
                    },
                    "type": {
                        "type": "string",
                        "title": "",
                        "enum": [
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ],
                        "description": "type of the object you want to fetch.",
                        "x-examples": {},
                    },
                },
                "required": ["id", "type"],
            },
        },
    )


class PipelessEditObjectConfig(_Input):
    "Edit the properties of an existing object."
    operation: Literal["edit_object"] = Field(
        "edit_object", json_schema_extra={"ui:hidden": True}
    )
    object: Annotated[
        str, BeforeValidator(lambda value: _json_input(value, models.ObjectLookup))
    ] = Field(
        ...,
        title="Object",
        description="The existing object that is to be modified.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "title": "",
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "title": "",
                        "minLength": 1,
                        "maxLength": 40,
                        "description": "id of the object you want to fetch.",
                    },
                    "type": {
                        "type": "string",
                        "title": "",
                        "enum": [
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ],
                        "description": "type of the object you want to fetch.",
                        "x-examples": {},
                    },
                },
                "required": ["id", "type"],
                "description": "The existing object that is to be modified.",
            },
        },
    )
    new_props: Annotated[
        str,
        BeforeValidator(lambda value: _json_input(value, models.EditObjectNewProps)),
    ] = Field(
        ...,
        title="New props",
        description="New properties to be set for the object.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "type": "object",
                "description": "New properties to be set for the object.",
                "properties": {
                    "id": {
                        "type": "string",
                        "title": "",
                        "minLength": 1,
                        "maxLength": 40,
                        "description": "New id for the object. If not included, the current id will be kept.",
                    },
                    "created_on": {
                        "type": "string",
                        "format": "date-time",
                        "description": "New created_on (in datetime format) for the object. If not included, the current value will be kept.",
                    },
                    "modified_on": {
                        "type": "string",
                        "format": "date-time",
                        "description": "New modified_on (in datetime format) for the object. If not included, the current value will be kept.",
                    },
                },
            },
        },
    )


class PipelessGetActivityOnObjectConfig(_Input):
    "Get activity that has taken place on a target object."
    operation: Literal["get_activity_on_object"] = Field(
        "get_activity_on_object", json_schema_extra={"ui:hidden": True}
    )
    object: Annotated[
        str, BeforeValidator(lambda value: _json_input(value, models.ObjectLookup))
    ] = Field(
        ...,
        title="Object",
        description="Specify the id and type of the object that you want to fetch the activity for.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "title": "",
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "title": "",
                        "minLength": 1,
                        "maxLength": 40,
                        "description": "id of the object you want to fetch.",
                    },
                    "type": {
                        "type": "string",
                        "title": "",
                        "enum": [
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ],
                        "description": "type of the object you want to fetch.",
                        "x-examples": {},
                    },
                },
                "required": ["id", "type"],
                "description": "Specify the id and type of the object that you want to fetch the activity for.",
            },
        },
    )
    relationship_types: Optional[
        Annotated[
            str,
            BeforeValidator(
                lambda value: _json_input(
                    value,
                    list[
                        Literal[
                            "posted",
                            "followed",
                            "liked",
                            "favorited",
                            "saved",
                            "unsaved",
                            "disliked",
                            "purchased",
                            "commentedOn",
                            "created",
                            "viewed",
                            "reported",
                            "blocked",
                            "deleted",
                            "authored",
                            "used",
                            "dismissed",
                            "loggedIn",
                            "taggedWith",
                            "categorizedIn",
                            "interestedIn",
                            "locatedIn",
                            "readQuarter",
                            "readHalf",
                            "readAll",
                            "subscribedTo",
                            "subscribedFrom",
                            "addedTo",
                            "madeBy",
                            "pausedOn",
                            "updated",
                            "enabled",
                            "disabled",
                        ]
                    ],
                )
            ),
        ]
    ] = Field(
        None,
        title="Relationship types",
        description="Relationship types to include in the fetched activity (will include all by default)",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "type": "array",
                "uniqueItems": False,
                "description": "Relationship types to include in the fetched activity (will include all by default)",
                "items": {
                    "type": "string",
                    "enum": [
                        "posted",
                        "followed",
                        "liked",
                        "favorited",
                        "saved",
                        "unsaved",
                        "disliked",
                        "purchased",
                        "commentedOn",
                        "created",
                        "viewed",
                        "reported",
                        "blocked",
                        "deleted",
                        "authored",
                        "used",
                        "dismissed",
                        "loggedIn",
                        "taggedWith",
                        "categorizedIn",
                        "interestedIn",
                        "locatedIn",
                        "readQuarter",
                        "readHalf",
                        "readAll",
                        "subscribedTo",
                        "subscribedFrom",
                        "addedTo",
                        "madeBy",
                        "pausedOn",
                        "updated",
                        "enabled",
                        "disabled",
                    ],
                    "title": "",
                    "description": "The type of relationship for an event. Can be any one of our predefined types. Although it is flexible what relationship type you use, as a best practice, we suggest you pick the one that relates best to the data you are representing. Doing this also allows specific algos to automatically work with their default settings.",
                },
            },
        },
    )
    direction: Optional[Literal["outgoing", "incoming", "all"]] = Field(
        None,
        title="Direction",
        description="Direction of relationships to include in the acitivty on the specified object. If no direciton is speciifed, activity event relationships of both directions will be returned.",
    )
    return_cursor_for_events: Optional[bool] = Field(
        None,
        title="Return cursor for events",
        description="This value defaults to false. When set to true, each returned event will contain an additional property called cursor, which contains the cursor value for that specific item. Just like end_cusror in page_info, any cursor value can be used in the before param to begin pagination after the specified cursor.",
    )
    limit: Optional[int] = Field(None, title="Limit")
    before: Optional[str] = Field(None, title="Before")


class PipelessGetActivityFeedConfig(_Input):
    "Fetch the activity feed for a user (or any other object type). This activity feed format will return events in sequential descending order - there will be one activity item for each found action."
    operation: Literal["get_activity_feed"] = Field(
        "get_activity_feed", json_schema_extra={"ui:hidden": True}
    )
    object: Annotated[
        str, BeforeValidator(lambda value: _json_input(value, models.ObjectLookup))
    ] = Field(
        ...,
        title="Object",
        description="The object (ex. user) you want to fetch the activity feed for.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "title": "",
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "title": "",
                        "minLength": 1,
                        "maxLength": 40,
                        "description": "id of the object you want to fetch.",
                    },
                    "type": {
                        "type": "string",
                        "title": "",
                        "enum": [
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ],
                        "description": "type of the object you want to fetch.",
                        "x-examples": {},
                    },
                },
                "required": ["id", "type"],
                "description": "The object (ex. user) you want to fetch the activity feed for.",
            },
        },
    )
    follow_relationship_types: Optional[
        Annotated[
            str,
            BeforeValidator(
                lambda value: _json_input(
                    value,
                    list[
                        Literal[
                            "posted",
                            "followed",
                            "liked",
                            "favorited",
                            "saved",
                            "unsaved",
                            "disliked",
                            "purchased",
                            "commentedOn",
                            "created",
                            "viewed",
                            "reported",
                            "blocked",
                            "deleted",
                            "authored",
                            "used",
                            "dismissed",
                            "loggedIn",
                            "taggedWith",
                            "categorizedIn",
                            "interestedIn",
                            "locatedIn",
                            "readQuarter",
                            "readHalf",
                            "readAll",
                            "subscribedTo",
                            "subscribedFrom",
                            "addedTo",
                            "madeBy",
                            "pausedOn",
                            "updated",
                            "enabled",
                            "disabled",
                        ]
                    ],
                )
            ),
        ]
    ] = Field(
        None,
        title="Follow relationship types",
        description='An array of the relationship types that represent the concept of "following" in your data. If none provided, by default the relationship type "followed" will be used.',
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "posted",
                        "followed",
                        "liked",
                        "favorited",
                        "saved",
                        "unsaved",
                        "disliked",
                        "purchased",
                        "commentedOn",
                        "created",
                        "viewed",
                        "reported",
                        "blocked",
                        "deleted",
                        "authored",
                        "used",
                        "dismissed",
                        "loggedIn",
                        "taggedWith",
                        "categorizedIn",
                        "interestedIn",
                        "locatedIn",
                        "readQuarter",
                        "readHalf",
                        "readAll",
                        "subscribedTo",
                        "subscribedFrom",
                        "addedTo",
                        "madeBy",
                        "pausedOn",
                        "updated",
                        "enabled",
                        "disabled",
                    ],
                },
                "description": 'An array of the relationship types that represent the concept of "following" in your data. If none provided, by default the relationship type "followed" will be used.',
            },
        },
    )
    follow_object_types: Optional[
        Annotated[
            str,
            BeforeValidator(
                lambda value: _json_input(
                    value,
                    list[
                        Literal[
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ]
                    ],
                )
            ),
        ]
    ] = Field(
        None,
        title="Follow object types",
        description="An array of the object types that can be followed in your dataset and that you want to be used for this activity feed. If none provided, by default any object type that is found based on the allowed follow_relationship_types will be used.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "user",
                        "product",
                        "image",
                        "comment",
                        "article",
                        "post",
                        "video",
                        "content",
                        "tag",
                        "category",
                        "app",
                        "book",
                        "person",
                        "skill",
                        "job",
                        "company",
                        "account",
                        "card",
                        "country",
                        "state",
                        "film",
                        "cart",
                        "document",
                        "project",
                    ],
                },
                "description": "An array of the object types that can be followed in your dataset and that you want to be used for this activity feed. If none provided, by default any object type that is found based on the allowed follow_relationship_types will be used.",
            },
        },
    )
    event_relationship_types: Optional[
        Annotated[
            str,
            BeforeValidator(
                lambda value: _json_input(
                    value,
                    list[
                        Literal[
                            "posted",
                            "followed",
                            "liked",
                            "favorited",
                            "saved",
                            "unsaved",
                            "disliked",
                            "purchased",
                            "commentedOn",
                            "created",
                            "viewed",
                            "reported",
                            "blocked",
                            "deleted",
                            "authored",
                            "used",
                            "dismissed",
                            "loggedIn",
                            "taggedWith",
                            "categorizedIn",
                            "interestedIn",
                            "locatedIn",
                            "readQuarter",
                            "readHalf",
                            "readAll",
                            "subscribedTo",
                            "subscribedFrom",
                            "addedTo",
                            "madeBy",
                            "pausedOn",
                            "updated",
                            "enabled",
                            "disabled",
                        ]
                    ],
                )
            ),
        ]
    ] = Field(
        None,
        title="Event relationship types",
        description="An array of the relationship types of the actions you want to show up in the activity feed. If none provided, by default any relationships that are present in the resulting feed items will be returned.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "posted",
                        "followed",
                        "liked",
                        "favorited",
                        "saved",
                        "unsaved",
                        "disliked",
                        "purchased",
                        "commentedOn",
                        "created",
                        "viewed",
                        "reported",
                        "blocked",
                        "deleted",
                        "authored",
                        "used",
                        "dismissed",
                        "loggedIn",
                        "taggedWith",
                        "categorizedIn",
                        "interestedIn",
                        "locatedIn",
                        "readQuarter",
                        "readHalf",
                        "readAll",
                        "subscribedTo",
                        "subscribedFrom",
                        "addedTo",
                        "madeBy",
                        "pausedOn",
                        "updated",
                        "enabled",
                        "disabled",
                    ],
                },
                "description": "An array of the relationship types of the actions you want to show up in the activity feed. If none provided, by default any relationships that are present in the resulting feed items will be returned.",
            },
        },
    )
    event_object_types: Optional[
        Annotated[
            str,
            BeforeValidator(
                lambda value: _json_input(
                    value,
                    list[
                        Literal[
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ]
                    ],
                )
            ),
        ]
    ] = Field(
        None,
        title="Event object types",
        description="An array of the object types that can appear as content in the feed. If none provided, any object type that results from the other settings will be shown in the feed.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "user",
                        "product",
                        "image",
                        "comment",
                        "article",
                        "post",
                        "video",
                        "content",
                        "tag",
                        "category",
                        "app",
                        "book",
                        "person",
                        "skill",
                        "job",
                        "company",
                        "account",
                        "card",
                        "country",
                        "state",
                        "film",
                        "cart",
                        "document",
                        "project",
                    ],
                },
                "description": "An array of the object types that can appear as content in the feed. If none provided, any object type that results from the other settings will be shown in the feed.",
            },
        },
    )
    exclude_self_object: Optional[bool] = Field(
        None,
        title="Exclude self object",
        description="If this value is false (the default), then the user you are fetching the feed for can appear in the feed results as an acting user (if the user follows themself) or action user (object that is being acted on by users the user follows). If set to true, the user the feed is being fetched for will not appear in the results.",
    )
    allow_missing_object: Optional[bool] = Field(
        None,
        title="Allow missing object",
        description="If this value is false (the default), then trying to fetch an activity feed for a non-existent object will result in a 404 object not found error being returned. If this value is true, then in the case of a non-existent object, an empty activity feed will be returned with no error.",
    )
    return_cursor_for_events: Optional[bool] = Field(
        None,
        title="Return cursor for events",
        description="This value defaults to false. When set to true, each returned event will contain an additional property called cursor, which contains the cursor value for that specific item. Just like end_cusror in page_info, any cursor value can be used in the before param to begin pagination after the specified cursor.",
    )
    limit: Optional[int] = Field(None, title="Limit")
    before: Optional[str] = Field(None, title="Before")


class PipelessGetActivityActionsFeedConfig(_Input):
    "Fetch the activity feed for a user (or any other object type). This activity feed format will return acted upon entities as the main result. Ex. one item per post, article, product, etc. Each single item has associated actions. Ex. product a product"
    operation: Literal["get_activity_actions_feed"] = Field(
        "get_activity_actions_feed", json_schema_extra={"ui:hidden": True}
    )
    object: Annotated[
        str, BeforeValidator(lambda value: _json_input(value, models.ObjectLookup))
    ] = Field(
        ...,
        title="Object",
        description="The object (ex. user) you want to fetch the activity feed for.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "title": "",
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "title": "",
                        "minLength": 1,
                        "maxLength": 40,
                        "description": "id of the object you want to fetch.",
                    },
                    "type": {
                        "type": "string",
                        "title": "",
                        "enum": [
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ],
                        "description": "type of the object you want to fetch.",
                        "x-examples": {},
                    },
                },
                "required": ["id", "type"],
                "description": "The object (ex. user) you want to fetch the activity feed for.",
            },
        },
    )
    follow_relationship_types: Optional[
        Annotated[
            str,
            BeforeValidator(
                lambda value: _json_input(
                    value,
                    list[
                        Literal[
                            "posted",
                            "followed",
                            "liked",
                            "favorited",
                            "saved",
                            "unsaved",
                            "disliked",
                            "purchased",
                            "commentedOn",
                            "created",
                            "viewed",
                            "reported",
                            "blocked",
                            "deleted",
                            "authored",
                            "used",
                            "dismissed",
                            "loggedIn",
                            "taggedWith",
                            "categorizedIn",
                            "interestedIn",
                            "locatedIn",
                            "readQuarter",
                            "readHalf",
                            "readAll",
                            "subscribedTo",
                            "subscribedFrom",
                            "addedTo",
                            "madeBy",
                            "pausedOn",
                            "updated",
                            "enabled",
                            "disabled",
                        ]
                    ],
                )
            ),
        ]
    ] = Field(
        None,
        title="Follow relationship types",
        description='An array of the relationship types that represent the concept of "following" in your data. If none provided, by default the relationship type "followed" will be used.',
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "posted",
                        "followed",
                        "liked",
                        "favorited",
                        "saved",
                        "unsaved",
                        "disliked",
                        "purchased",
                        "commentedOn",
                        "created",
                        "viewed",
                        "reported",
                        "blocked",
                        "deleted",
                        "authored",
                        "used",
                        "dismissed",
                        "loggedIn",
                        "taggedWith",
                        "categorizedIn",
                        "interestedIn",
                        "locatedIn",
                        "readQuarter",
                        "readHalf",
                        "readAll",
                        "subscribedTo",
                        "subscribedFrom",
                        "addedTo",
                        "madeBy",
                        "pausedOn",
                        "updated",
                        "enabled",
                        "disabled",
                    ],
                },
                "description": 'An array of the relationship types that represent the concept of "following" in your data. If none provided, by default the relationship type "followed" will be used.',
            },
        },
    )
    follow_object_types: Optional[
        Annotated[
            str,
            BeforeValidator(
                lambda value: _json_input(
                    value,
                    list[
                        Literal[
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ]
                    ],
                )
            ),
        ]
    ] = Field(
        None,
        title="Follow object types",
        description="An array of the object types that can be followed in your dataset and that you want to be used for this activity feed. If none provided, by default any object type that is found based on the allowed follow_relationship_types will be used.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "user",
                        "product",
                        "image",
                        "comment",
                        "article",
                        "post",
                        "video",
                        "content",
                        "tag",
                        "category",
                        "app",
                        "book",
                        "person",
                        "skill",
                        "job",
                        "company",
                        "account",
                        "card",
                        "country",
                        "state",
                        "film",
                        "cart",
                        "document",
                        "project",
                    ],
                },
                "description": "An array of the object types that can be followed in your dataset and that you want to be used for this activity feed. If none provided, by default any object type that is found based on the allowed follow_relationship_types will be used.",
            },
        },
    )
    event_relationship_types: Optional[
        Annotated[
            str,
            BeforeValidator(
                lambda value: _json_input(
                    value,
                    list[
                        Literal[
                            "posted",
                            "followed",
                            "liked",
                            "favorited",
                            "saved",
                            "unsaved",
                            "disliked",
                            "purchased",
                            "commentedOn",
                            "created",
                            "viewed",
                            "reported",
                            "blocked",
                            "deleted",
                            "authored",
                            "used",
                            "dismissed",
                            "loggedIn",
                            "taggedWith",
                            "categorizedIn",
                            "interestedIn",
                            "locatedIn",
                            "readQuarter",
                            "readHalf",
                            "readAll",
                            "subscribedTo",
                            "subscribedFrom",
                            "addedTo",
                            "madeBy",
                            "pausedOn",
                            "updated",
                            "enabled",
                            "disabled",
                        ]
                    ],
                )
            ),
        ]
    ] = Field(
        None,
        title="Event relationship types",
        description="An array of the relationship types of the actions you want to show up in the activity feed. If none provided, by default any relationships that are present in the resulting feed items will be returned.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "posted",
                        "followed",
                        "liked",
                        "favorited",
                        "saved",
                        "unsaved",
                        "disliked",
                        "purchased",
                        "commentedOn",
                        "created",
                        "viewed",
                        "reported",
                        "blocked",
                        "deleted",
                        "authored",
                        "used",
                        "dismissed",
                        "loggedIn",
                        "taggedWith",
                        "categorizedIn",
                        "interestedIn",
                        "locatedIn",
                        "readQuarter",
                        "readHalf",
                        "readAll",
                        "subscribedTo",
                        "subscribedFrom",
                        "addedTo",
                        "madeBy",
                        "pausedOn",
                        "updated",
                        "enabled",
                        "disabled",
                    ],
                },
                "description": "An array of the relationship types of the actions you want to show up in the activity feed. If none provided, by default any relationships that are present in the resulting feed items will be returned.",
            },
        },
    )
    event_object_types: Optional[
        Annotated[
            str,
            BeforeValidator(
                lambda value: _json_input(
                    value,
                    list[
                        Literal[
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ]
                    ],
                )
            ),
        ]
    ] = Field(
        None,
        title="Event object types",
        description="An array of the object types that can appear as content in the feed. If none provided, any object type that results from the other settings will be shown in the feed.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "user",
                        "product",
                        "image",
                        "comment",
                        "article",
                        "post",
                        "video",
                        "content",
                        "tag",
                        "category",
                        "app",
                        "book",
                        "person",
                        "skill",
                        "job",
                        "company",
                        "account",
                        "card",
                        "country",
                        "state",
                        "film",
                        "cart",
                        "document",
                        "project",
                    ],
                },
                "description": "An array of the object types that can appear as content in the feed. If none provided, any object type that results from the other settings will be shown in the feed.",
            },
        },
    )
    exclude_self_object: Optional[bool] = Field(
        None,
        title="Exclude self object",
        description="If this value is false (the default), then the user you are fetching the feed for can appear in the feed results as an acting user (if the user follows themself) or action user (object that is being acted on by users the user follows). If set to true, the user the feed is being fetched for will not appear in the results.",
    )
    allow_missing_object: Optional[bool] = Field(
        None,
        title="Allow missing object",
        description="If this value is false (the default), then trying to fetch an activity feed for a non-existent object will result in a 404 object not found error being returned. If this value is true, then in the case of a non-existent object, an empty activity feed will be returned with no error.",
    )
    return_cursor_for_events: Optional[bool] = Field(
        None,
        title="Return cursor for events",
        description="This value defaults to false. When set to true, each returned event will contain an additional property called cursor, which contains the cursor value for that specific item. Just like end_cusror in page_info, any cursor value can be used in the before param to begin pagination after the specified cursor.",
    )
    limit: Optional[int] = Field(None, title="Limit")
    before: Optional[str] = Field(None, title="Before")


class PipelessGetRecentEventsConfig(_Input):
    "Get recent events that have been sent to the specified app."
    operation: Literal["get_recent_events"] = Field(
        "get_recent_events", json_schema_extra={"ui:hidden": True}
    )
    limit: Optional[int] = Field(None, title="Limit", ge=1, le=100)


class PipelessGetRecommendedContentConfig(_Input):
    "Gets recommeneded content for a given object (ex. recommended posts for a user based on their previous actions, collaborative filtering, and tags associated with the content they interacted with)."
    operation: Literal["get_recommended_content"] = Field(
        "get_recommended_content", json_schema_extra={"ui:hidden": True}
    )
    object: Annotated[
        str, BeforeValidator(lambda value: _json_input(value, models.ObjectLookup))
    ] = Field(
        ...,
        title="Object",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "title": "",
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "title": "",
                        "minLength": 1,
                        "maxLength": 40,
                        "description": "id of the object you want to fetch.",
                    },
                    "type": {
                        "type": "string",
                        "title": "",
                        "enum": [
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ],
                        "description": "type of the object you want to fetch.",
                        "x-examples": {},
                    },
                },
                "required": ["id", "type"],
            },
        },
    )
    content_object_type: Literal[
        "user",
        "product",
        "image",
        "comment",
        "article",
        "post",
        "video",
        "content",
        "tag",
        "category",
        "app",
        "book",
        "person",
        "skill",
        "job",
        "company",
        "account",
        "card",
        "country",
        "state",
        "film",
        "cart",
        "document",
        "project",
    ] = Field(
        ...,
        title="Content object type",
        description="The type of object that is being recommended.",
    )
    primary_positive_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Primary positive relationship type",
        description='The primary positive indicator a user can take on the content type that\'s being recommended. This should be the action a user can take that you consider most important to indicating that an object appeals to their tastes. If value is not provided, it will default to "liked".',
    )
    secondary_positive_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Secondary positive relationship type",
        description='The secondary positive indicator a user can take on the content type that\'s being recommended. This should be the action a user can take that you consider to be important in indicating that an object appeals to their tastes. It will be weighted less than the primary positive relationship type, but still taken into account. If value is not provided, it will default to "viewed".',
    )
    primary_negative_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Primary negative relationship type",
        description='The primary negative action a user can take on the content type. This should be the action a user can take that you consider to be important in indicating that an object does not appeal to their tastes. Content that the user marked with this type will not be returned in recommendation results. If value is not provided, it will default to "disliked".',
    )
    content_tagged_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Content tagged relationship type",
        description='Set this relationship to the relationship you use to set tags on the content that is being recommended. If a value is not provided, "taggedWith" will be used by default.',
    )
    content_tag_object_type: Optional[
        Literal[
            "user",
            "product",
            "image",
            "comment",
            "article",
            "post",
            "video",
            "content",
            "tag",
            "category",
            "app",
            "book",
            "person",
            "skill",
            "job",
            "company",
            "account",
            "card",
            "country",
            "state",
            "film",
            "cart",
            "document",
            "project",
        ]
    ] = Field(
        None,
        title="Content tag object type",
        description='Set this relationship to the object you use for tags on the content that is being recommended. If a value is not provided, "tag" will be used by default.',
    )
    coldstart_tag_ids: Optional[
        Annotated[str, BeforeValidator(lambda value: _json_input(value, list[str]))]
    ] = Field(
        None,
        title="Coldstart tag ids",
        description="You can use this option to provide some ids of tags you want to contribute to coldstart recommendations if no real recommendations are yet available for a user. If you provide one or more tag ids for this field, trending content from those tags will be used as coldstart recommendations when personalized recommendations are not available.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "type": "array",
                "description": "You can use this option to provide some ids of tags you want to contribute to coldstart recommendations if no real recommendations are yet available for a user. If you provide one or more tag ids for this field, trending content from those tags will be used as coldstart recommendations when personalized recommendations are not available.",
                "items": {
                    "type": "string",
                    "title": "",
                    "minLength": 1,
                    "maxLength": 40,
                },
            },
        },
    )
    filter_tag_ids: Optional[
        Annotated[str, BeforeValidator(lambda value: _json_input(value, list[str]))]
    ] = Field(
        None,
        title="Filter tag ids",
        description="You can use this option to provide ids of tags that will be used to filter the returned recommended content. If any tag ids are specified in this value, then a piece of recommended content will only be returned if it is tagged (using specified content_tagged_relationship_type) with all of the tags provided in this option.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "type": "array",
                "description": "You can use this option to provide ids of tags that will be used to filter the returned recommended content. If any tag ids are specified in this value, then a piece of recommended content will only be returned if it is tagged (using specified content_tagged_relationship_type) with all of the tags provided in this option.",
                "items": {
                    "type": "string",
                    "title": "",
                    "minLength": 1,
                    "maxLength": 40,
                },
            },
        },
    )
    include_content_authors: Optional[bool] = Field(
        None,
        title="Include content authors",
        description="Default value is false. If set to true, an array called authors will be provided with each item, providing the authors of the recommended content. If this is set to true, then content_created_relationship_type must also be set.",
    )
    content_created_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Content created relationship type",
        description="A relationship type that represents a user creating content in your data. Required if include_content_authors or exclude_content_from_followed is set to true.",
    )
    exclude_content_from_followed: Optional[bool] = Field(
        None,
        title="Exclude content from followed",
        description="Default value is false. If set to true, content that was created by authors that the user follows will be excluded. If set to true, content_created_relationship_type must also be set.",
    )
    followed_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Followed relationship type",
        description="A relationship type that represents a user following another user in your data. If exclude_content_from_followed is set to true and this value is not set, then it will default to followed.",
    )
    dismissed_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Dismissed relationship type",
        description='A relationship type that represents a user dismissing the recommendation of a piece of content in your data. If this param is not provided, it defaults to "dismissed".',
    )
    limit: Optional[int] = Field(None, title="Limit")


class PipelessGetSortedContentConfig(_Input):
    "Provide a set of content ids, and this algo will rank and sort the given ids based on the given user's previous actions, collaborative filtering, and tags associated with the content they interacted with."
    operation: Literal["get_sorted_content"] = Field(
        "get_sorted_content", json_schema_extra={"ui:hidden": True}
    )
    object: Annotated[
        str, BeforeValidator(lambda value: _json_input(value, models.ObjectLookup))
    ] = Field(
        ...,
        title="Object",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "title": "",
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "title": "",
                        "minLength": 1,
                        "maxLength": 40,
                        "description": "id of the object you want to fetch.",
                    },
                    "type": {
                        "type": "string",
                        "title": "",
                        "enum": [
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ],
                        "description": "type of the object you want to fetch.",
                        "x-examples": {},
                    },
                },
                "required": ["id", "type"],
            },
        },
    )
    content_object_type: Literal[
        "user",
        "product",
        "image",
        "comment",
        "article",
        "post",
        "video",
        "content",
        "tag",
        "category",
        "app",
        "book",
        "person",
        "skill",
        "job",
        "company",
        "account",
        "card",
        "country",
        "state",
        "film",
        "cart",
        "document",
        "project",
    ] = Field(
        ...,
        title="Content object type",
        description="The type of object that your content_ids (items to sort) are of.",
    )
    content_ids: Annotated[
        str, BeforeValidator(lambda value: _json_input(value, list[str]))
    ] = Field(
        ...,
        title="Content ids",
        description="The ids of the content you want to sort. The ids must be for the type of content set in content_object_type.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "type": "array",
                "items": {
                    "type": "string",
                    "title": "",
                    "minLength": 1,
                    "maxLength": 40,
                },
                "description": "The ids of the content you want to sort. The ids must be for the type of content set in content_object_type.",
            },
        },
    )
    primary_positive_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Primary positive relationship type",
        description='The primary positive indicator a user can take on the content type that\'s being recommended. This should be the action a user can take that you consider most important to indicating that an object appeals to their tastes. If value is not provided, it will default to "liked".',
    )
    secondary_positive_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Secondary positive relationship type",
        description='The secondary positive indicator a user can take on the content type that\'s being recommended. This should be the action a user can take that you consider to be important in indicating that an object appeals to their tastes. It will be weighted less than the primary positive relationship type, but still taken into account. If value is not provided, it will default to "viewed".',
    )
    primary_negative_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Primary negative relationship type",
        description='The primary negative action a user can take on the content type. This should be the action a user can take that you consider to be important in indicating that an object does not appeal to their tastes. Content that the user marked with this type will not be returned in recommendation results. If value is not provided, it will default to "disliked".',
    )
    content_tagged_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Content tagged relationship type",
        description='Set this relationship to the relationship you use to set tags on the content that is being recommended. If a value is not provided, "taggedWith" will be used by default.',
    )
    content_tag_object_type: Optional[
        Literal[
            "user",
            "product",
            "image",
            "comment",
            "article",
            "post",
            "video",
            "content",
            "tag",
            "category",
            "app",
            "book",
            "person",
            "skill",
            "job",
            "company",
            "account",
            "card",
            "country",
            "state",
            "film",
            "cart",
            "document",
            "project",
        ]
    ] = Field(
        None,
        title="Content tag object type",
        description='Set this relationship to the object you use for tags on the content that is being recommended. If a value is not provided, "tag" will be used by default.',
    )
    limit: Optional[int] = Field(None, title="Limit")


class PipelessGetRecommendedUsersToFollowConfig(_Input):
    "For a given user (or any object type), get a list of recommended users for the target user to follow, based on their behavior/tastes."
    operation: Literal["get_recommended_users_to_follow"] = Field(
        "get_recommended_users_to_follow", json_schema_extra={"ui:hidden": True}
    )
    object: Annotated[
        str, BeforeValidator(lambda value: _json_input(value, models.ObjectLookup))
    ] = Field(
        ...,
        title="Object",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "title": "",
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "title": "",
                        "minLength": 1,
                        "maxLength": 40,
                        "description": "id of the object you want to fetch.",
                    },
                    "type": {
                        "type": "string",
                        "title": "",
                        "enum": [
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ],
                        "description": "type of the object you want to fetch.",
                        "x-examples": {},
                    },
                },
                "required": ["id", "type"],
            },
        },
    )
    followed_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Followed relationship type",
        description='The relationship type in your data that is used to represent a user (or other type) following someone else. If this value is not provided, it will default to "followed".',
    )
    content_created_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Content created relationship type",
        description='A relationship type that represents a user creating content in your data. If no value is provided, this will default to "posted".',
    )
    positive_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Positive relationship type",
        description='The positive indicator a user can take on the content type that users can create. This should be the action a user can take that you consider most important to indicating that an object appeals to their tastes. If value is not provided, it will default to "liked".',
    )
    content_tagged_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Content tagged relationship type",
        description='Set this relationship to the relationship you use to set tags on the content that is created by users. If a value is not provided, "taggedWith" will be used by default.',
    )
    content_object_type: Optional[
        Literal[
            "user",
            "product",
            "image",
            "comment",
            "article",
            "post",
            "video",
            "content",
            "tag",
            "category",
            "app",
            "book",
            "person",
            "skill",
            "job",
            "company",
            "account",
            "card",
            "country",
            "state",
            "film",
            "cart",
            "document",
            "project",
        ]
    ] = Field(
        None,
        title="Content object type",
        description='The type of object that represents the content being created by users. If no value is provided, this defaults to "post".\n',
    )
    content_tag_object_type: Optional[
        Literal[
            "user",
            "product",
            "image",
            "comment",
            "article",
            "post",
            "video",
            "content",
            "tag",
            "category",
            "app",
            "book",
            "person",
            "skill",
            "job",
            "company",
            "account",
            "card",
            "country",
            "state",
            "film",
            "cart",
            "document",
            "project",
        ]
    ] = Field(
        None,
        title="Content tag object type",
        description='Set this type to the object you use for tags on the content that is created by your users. If a value is not provided, "tag" will be used by default.',
    )
    dismissed_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Dismissed relationship type",
        description='A relationship type that represents a user dismissing the recommendation of a piece of content in your data. If this param is not provided, it defaults to "dismissed".',
    )
    allow_missing_object: Optional[bool] = Field(
        None,
        title="Allow missing object",
        description="If this value is false (the default), then trying to fetch an activity feed for a non-existent object will result in a 404 object not found error being returned. If this value is true, then in the case of a non-existent object, an empty activity feed will be returned with no error.",
    )
    limit: Optional[int] = Field(None, title="Limit")


class PipelessGetRelatedTagsConfig(_Input):
    "Gets related tags for a given tag (or any other object type, ex. category)."
    operation: Literal["get_related_tags"] = Field(
        "get_related_tags", json_schema_extra={"ui:hidden": True}
    )
    object: Annotated[
        str, BeforeValidator(lambda value: _json_input(value, models.ObjectLookup))
    ] = Field(
        ...,
        title="Object",
        description="The object (ex. a tag, category, etc.) that you want to get related objects for. The related objects will be of the same type as this provided object.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "title": "",
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "title": "",
                        "minLength": 1,
                        "maxLength": 40,
                        "description": "id of the object you want to fetch.",
                    },
                    "type": {
                        "type": "string",
                        "title": "",
                        "enum": [
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ],
                        "description": "type of the object you want to fetch.",
                        "x-examples": {},
                    },
                },
                "required": ["id", "type"],
                "description": "The object (ex. a tag, category, etc.) that you want to get related objects for. The related objects will be of the same type as this provided object.",
            },
        },
    )
    content_object_type: Literal[
        "user",
        "product",
        "image",
        "comment",
        "article",
        "post",
        "video",
        "content",
        "tag",
        "category",
        "app",
        "book",
        "person",
        "skill",
        "job",
        "company",
        "account",
        "card",
        "country",
        "state",
        "film",
        "cart",
        "document",
        "project",
    ] = Field(
        ...,
        title="Content object type",
        description='The object type of the content associated to your tags. Ex. if the tags in your dataset are found on posts, then this value should be "post".',
    )
    content_tagged_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Content tagged relationship type",
        description="The relationship type that represents content being tagged in your set. If no value is provided, this will default to taggedWith.",
    )
    disregard_tag_ids: Optional[
        Annotated[str, BeforeValidator(lambda value: _json_input(value, list[str]))]
    ] = Field(
        None,
        title="Disregard tag ids",
        description="Object ids that you want not to be included in the resulting tags (or whatever type target object is).",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "type": "array",
                "description": "Object ids that you want not to be included in the resulting tags (or whatever type target object is).",
                "items": {
                    "type": "string",
                    "title": "",
                    "minLength": 1,
                    "maxLength": 40,
                },
            },
        },
    )


class PipelessGetRelatedContentConfig(_Input):
    "Gets related content objects based on a specific piece of content of any type."
    operation: Literal["get_related_content"] = Field(
        "get_related_content", json_schema_extra={"ui:hidden": True}
    )
    object: Annotated[
        str, BeforeValidator(lambda value: _json_input(value, models.ObjectLookup))
    ] = Field(
        ...,
        title="Object",
        description="The object you want to get related content for. All returned related content will be of the same type as this object.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "title": "",
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "title": "",
                        "minLength": 1,
                        "maxLength": 40,
                        "description": "id of the object you want to fetch.",
                    },
                    "type": {
                        "type": "string",
                        "title": "",
                        "enum": [
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ],
                        "description": "type of the object you want to fetch.",
                        "x-examples": {},
                    },
                },
                "required": ["id", "type"],
                "description": "The object you want to get related content for. All returned related content will be of the same type as this object.",
            },
        },
    )
    content_tagged_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Content tagged relationship type",
        description="The relationship type that represents content being tagged with a tag in your data. If not provided, then tags will not be considered in this algo.",
    )
    content_tagged_object_type: Optional[
        Literal[
            "user",
            "product",
            "image",
            "comment",
            "article",
            "post",
            "video",
            "content",
            "tag",
            "category",
            "app",
            "book",
            "person",
            "skill",
            "job",
            "company",
            "account",
            "card",
            "country",
            "state",
            "film",
            "cart",
            "document",
            "project",
        ]
    ] = Field(
        None,
        title="Content tagged object type",
        description='The object type that represents a tag in your data. If not provided, and content tagged relationship type was provided, this will default to "tag".',
    )
    positive_rel: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Positive rel",
        description="The relationship of a positive action that users (or whatever actor type) can take on the content type. If the value is not provided, then collabrative filtering will not be used in the algo.",
    )
    actor_object_type: Optional[
        Literal[
            "user",
            "product",
            "image",
            "comment",
            "article",
            "post",
            "video",
            "content",
            "tag",
            "category",
            "app",
            "book",
            "person",
            "skill",
            "job",
            "company",
            "account",
            "card",
            "country",
            "state",
            "film",
            "cart",
            "document",
            "project",
        ]
    ] = Field(
        None,
        title="Actor object type",
        description='The type of the object that acts on the target content (ex. user). If this value is not provided, and positive rel is set, then this will default to "user".',
    )


class PipelessGetRelatedUsersConfig(_Input):
    "Get related users based on a target user (or other type)."
    operation: Literal["get_related_users"] = Field(
        "get_related_users", json_schema_extra={"ui:hidden": True}
    )
    object: Annotated[
        str, BeforeValidator(lambda value: _json_input(value, models.ObjectLookup))
    ] = Field(
        ...,
        title="Object",
        description="The object (generally a user) that you want to get recommended items for. The returned items will be of the same type as this object.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "title": "",
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "title": "",
                        "minLength": 1,
                        "maxLength": 40,
                        "description": "id of the object you want to fetch.",
                    },
                    "type": {
                        "type": "string",
                        "title": "",
                        "enum": [
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ],
                        "description": "type of the object you want to fetch.",
                        "x-examples": {},
                    },
                },
                "required": ["id", "type"],
                "description": "The object (generally a user) that you want to get recommended items for. The returned items will be of the same type as this object.",
            },
        },
    )
    followed_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Followed relationship type",
        description="The relationship type used to represent a user following another user. If this value is not provided, then collabrative filtering will not be used for the algo.",
    )
    content_tagged_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Content tagged relationship type",
        description="The relationship type that represents content (created by users) being tagged. If this value is not provided, then tag data will not be used for the algo.",
    )
    content_tagged_object_type: Optional[
        Literal[
            "user",
            "product",
            "image",
            "comment",
            "article",
            "post",
            "video",
            "content",
            "tag",
            "category",
            "app",
            "book",
            "person",
            "skill",
            "job",
            "company",
            "account",
            "card",
            "country",
            "state",
            "film",
            "cart",
            "document",
            "project",
        ]
    ] = Field(
        None,
        title="Content tagged object type",
        description='The object type that represents a tag for the content a user can publish. If this value is not set, and content tagged relationship type has been set, then this will default to "tag".',
    )
    content_object_type: Optional[
        Literal[
            "user",
            "product",
            "image",
            "comment",
            "article",
            "post",
            "video",
            "content",
            "tag",
            "category",
            "app",
            "book",
            "person",
            "skill",
            "job",
            "company",
            "account",
            "card",
            "country",
            "state",
            "film",
            "cart",
            "document",
            "project",
        ]
    ] = Field(
        None,
        title="Content object type",
        description='Object type of the content users publish. If this value is not set, and content tagged relationship type has been set, then this value will default to "post".',
    )
    content_published_relationship_type: Optional[
        Literal[
            "posted",
            "followed",
            "liked",
            "favorited",
            "saved",
            "unsaved",
            "disliked",
            "purchased",
            "commentedOn",
            "created",
            "viewed",
            "reported",
            "blocked",
            "deleted",
            "authored",
            "used",
            "dismissed",
            "loggedIn",
            "taggedWith",
            "categorizedIn",
            "interestedIn",
            "locatedIn",
            "readQuarter",
            "readHalf",
            "readAll",
            "subscribedTo",
            "subscribedFrom",
            "addedTo",
            "madeBy",
            "pausedOn",
            "updated",
            "enabled",
            "disabled",
        ]
    ] = Field(
        None,
        title="Content published relationship type",
        description='Teh relationship type that represents a user publishing content. If this value is not set, and content tagged relationship type has been set, then this value will default to "posted".',
    )


class PipelessGetRelationshipCountsConfig(_Input):
    "Get the counts of 1 or 2 relationships from/to a given object."
    operation: Literal["get_relationship_counts"] = Field(
        "get_relationship_counts", json_schema_extra={"ui:hidden": True}
    )
    object: Annotated[
        str, BeforeValidator(lambda value: _json_input(value, models.ObjectLookup))
    ] = Field(
        ...,
        title="Object",
        description="The object to get the incoming/outgoing relationship counts for.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "title": "",
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "title": "",
                        "minLength": 1,
                        "maxLength": 40,
                        "description": "id of the object you want to fetch.",
                    },
                    "type": {
                        "type": "string",
                        "title": "",
                        "enum": [
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ],
                        "description": "type of the object you want to fetch.",
                        "x-examples": {},
                    },
                },
                "required": ["id", "type"],
                "description": "The object to get the incoming/outgoing relationship counts for.",
            },
        },
    )
    relationships: Annotated[
        str,
        BeforeValidator(
            lambda value: _json_input(
                value, list[models.GetRelationshipCountsRelationshipsItem]
            )
        ),
    ] = Field(
        ...,
        title="Relationships",
        description="An array of relationship types/directions and object types to get the counts for. You can specifiy one or two relationships to count.",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "description": "An array of relationship types/directions and object types to get the counts for. You can specifiy one or two relationships to count.",
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": [
                                "posted",
                                "followed",
                                "liked",
                                "favorited",
                                "saved",
                                "unsaved",
                                "disliked",
                                "purchased",
                                "commentedOn",
                                "created",
                                "viewed",
                                "reported",
                                "blocked",
                                "deleted",
                                "authored",
                                "used",
                                "dismissed",
                                "loggedIn",
                                "taggedWith",
                                "categorizedIn",
                                "interestedIn",
                                "locatedIn",
                                "readQuarter",
                                "readHalf",
                                "readAll",
                                "subscribedTo",
                                "subscribedFrom",
                                "addedTo",
                                "madeBy",
                                "pausedOn",
                                "updated",
                                "enabled",
                                "disabled",
                            ],
                            "title": "",
                            "description": "The type of relationship for an event. Can be any one of our predefined types. Although it is flexible what relationship type you use, as a best practice, we suggest you pick the one that relates best to the data you are representing. Doing this also allows specific algos to automatically work with their default settings.",
                        },
                        "direction": {
                            "type": "string",
                            "enum": ["incoming", "outgoing"],
                        },
                        "other_object_type": {
                            "type": "string",
                            "title": "",
                            "enum": [
                                "user",
                                "product",
                                "image",
                                "comment",
                                "article",
                                "post",
                                "video",
                                "content",
                                "tag",
                                "category",
                                "app",
                                "book",
                                "person",
                                "skill",
                                "job",
                                "company",
                                "account",
                                "card",
                                "country",
                                "state",
                                "film",
                                "cart",
                                "document",
                                "project",
                            ],
                            "description": "The type of an object. Can be any one of our predefined types. Although it is flexible what object type you use, as a best practice, we suggest you pick the one that relates best to the data you are representing. Doing this also allows specific algos to automatically work with their default settings.",
                            "x-examples": {},
                        },
                    },
                    "required": ["type", "direction", "other_object_type"],
                },
            },
        },
    )


class PipelessGetRelationshipExistsConfig(_Input):
    "Determines if a given relationship of a specific type exists from the specified object to the specified end object."
    operation: Literal["get_relationship_exists"] = Field(
        "get_relationship_exists", json_schema_extra={"ui:hidden": True}
    )
    object: Annotated[
        str, BeforeValidator(lambda value: _json_input(value, models.ObjectLookup))
    ] = Field(
        ...,
        title="Object",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "title": "",
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "title": "",
                        "minLength": 1,
                        "maxLength": 40,
                        "description": "id of the object you want to fetch.",
                    },
                    "type": {
                        "type": "string",
                        "title": "",
                        "enum": [
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ],
                        "description": "type of the object you want to fetch.",
                        "x-examples": {},
                    },
                },
                "required": ["id", "type"],
            },
        },
    )
    relationship_type: Literal[
        "posted",
        "followed",
        "liked",
        "favorited",
        "saved",
        "unsaved",
        "disliked",
        "purchased",
        "commentedOn",
        "created",
        "viewed",
        "reported",
        "blocked",
        "deleted",
        "authored",
        "used",
        "dismissed",
        "loggedIn",
        "taggedWith",
        "categorizedIn",
        "interestedIn",
        "locatedIn",
        "readQuarter",
        "readHalf",
        "readAll",
        "subscribedTo",
        "subscribedFrom",
        "addedTo",
        "madeBy",
        "pausedOn",
        "updated",
        "enabled",
        "disabled",
    ] = Field(..., title="Relationship type")
    end_object: Annotated[
        str, BeforeValidator(lambda value: _json_input(value, models.ObjectLookup))
    ] = Field(
        ...,
        title="End object",
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {
                "title": "",
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "title": "",
                        "minLength": 1,
                        "maxLength": 40,
                        "description": "id of the object you want to fetch.",
                    },
                    "type": {
                        "type": "string",
                        "title": "",
                        "enum": [
                            "user",
                            "product",
                            "image",
                            "comment",
                            "article",
                            "post",
                            "video",
                            "content",
                            "tag",
                            "category",
                            "app",
                            "book",
                            "person",
                            "skill",
                            "job",
                            "company",
                            "account",
                            "card",
                            "country",
                            "state",
                            "film",
                            "cart",
                            "document",
                            "project",
                        ],
                        "description": "type of the object you want to fetch.",
                        "x-examples": {},
                    },
                },
                "required": ["id", "type"],
            },
        },
    )


PipelessConfig = Annotated[
    Union[
        PipelessCreateEventConfig,
        PipelessDeleteEventConfig,
        PipelessCreateEventsBatchConfig,
        PipelessGetObjectConfig,
        PipelessDeleteObjectConfig,
        PipelessEditObjectConfig,
        PipelessGetActivityOnObjectConfig,
        PipelessGetActivityFeedConfig,
        PipelessGetActivityActionsFeedConfig,
        PipelessGetRecentEventsConfig,
        PipelessGetRecommendedContentConfig,
        PipelessGetSortedContentConfig,
        PipelessGetRecommendedUsersToFollowConfig,
        PipelessGetRelatedTagsConfig,
        PipelessGetRelatedContentConfig,
        PipelessGetRelatedUsersConfig,
        PipelessGetRelationshipCountsConfig,
        PipelessGetRelationshipExistsConfig,
    ],
    Field(discriminator="operation"),
]


class PipelessFullConfig(NodeConfig[PipelessConfig, PipelessAPIKeyCredential]):
    pass


ROUTES = {
    "create_event": ("POST", "/v1/apps/{app_id}/events", [201, 202]),
    "delete_event": ("DELETE", "/v1/apps/{app_id}/events", [202]),
    "create_events_batch": ("POST", "/v1/apps/{app_id}/events/batch", [201, 202]),
    "get_object": ("GET", "/v1/apps/{app_id}/objects", [200]),
    "delete_object": ("DELETE", "/v1/apps/{app_id}/objects", [202]),
    "edit_object": ("PATCH", "/v1/apps/{app_id}/objects", [200]),
    "get_activity_on_object": ("GET", "/v1/apps/{app_id}/algos/activity/object", [200]),
    "get_activity_feed": ("GET", "/v1/apps/{app_id}/algos/activity/feed", [200]),
    "get_activity_actions_feed": (
        "GET",
        "/v1/apps/{app_id}/algos/activity/actions-feed",
        [200],
    ),
    "get_recent_events": ("GET", "/v1/apps/{app_id}/recent-events", [200]),
    "get_recommended_content": (
        "GET",
        "/v1/apps/{app_id}/algos/recommendations/content",
        [200],
    ),
    "get_sorted_content": (
        "GET",
        "/v1/apps/{app_id}/algos/recommendations/sorted-content",
        [200],
    ),
    "get_recommended_users_to_follow": (
        "GET",
        "/v1/apps/{app_id}/algos/recommendations/users-to-follow",
        [200],
    ),
    "get_related_tags": (
        "GET",
        "/v1/apps/{app_id}/algos/recommendations/related-tags",
        [200],
    ),
    "get_related_content": (
        "GET",
        "/v1/apps/{app_id}/algos/recommendations/related-content",
        [200],
    ),
    "get_related_users": (
        "GET",
        "/v1/apps/{app_id}/algos/recommendations/related-users",
        [200],
    ),
    "get_relationship_counts": ("GET", "/v1/apps/{app_id}/relationship-counts", [200]),
    "get_relationship_exists": ("GET", "/v1/apps/{app_id}/relationship-exists", [200]),
}
BODY_FIELDS = {
    "create_event": ["event", "synchronous"],
    "delete_event": ["event"],
    "create_events_batch": ["events", "synchronous"],
    "get_object": ["object"],
    "delete_object": ["object"],
    "edit_object": ["object", "new_props"],
    "get_activity_on_object": [
        "object",
        "relationship_types",
        "direction",
        "return_cursor_for_events",
        "limit",
        "before",
    ],
    "get_activity_feed": [
        "object",
        "follow_relationship_types",
        "follow_object_types",
        "event_relationship_types",
        "event_object_types",
        "exclude_self_object",
        "allow_missing_object",
        "return_cursor_for_events",
        "limit",
        "before",
    ],
    "get_activity_actions_feed": [
        "object",
        "follow_relationship_types",
        "follow_object_types",
        "event_relationship_types",
        "event_object_types",
        "exclude_self_object",
        "allow_missing_object",
        "return_cursor_for_events",
        "limit",
        "before",
    ],
    "get_recent_events": ["limit"],
    "get_recommended_content": [
        "object",
        "content_object_type",
        "primary_positive_relationship_type",
        "secondary_positive_relationship_type",
        "primary_negative_relationship_type",
        "content_tagged_relationship_type",
        "content_tag_object_type",
        "coldstart_tag_ids",
        "filter_tag_ids",
        "include_content_authors",
        "content_created_relationship_type",
        "exclude_content_from_followed",
        "followed_relationship_type",
        "dismissed_relationship_type",
        "limit",
    ],
    "get_sorted_content": [
        "object",
        "content_object_type",
        "content_ids",
        "primary_positive_relationship_type",
        "secondary_positive_relationship_type",
        "primary_negative_relationship_type",
        "content_tagged_relationship_type",
        "content_tag_object_type",
        "limit",
    ],
    "get_recommended_users_to_follow": [
        "object",
        "followed_relationship_type",
        "content_created_relationship_type",
        "positive_relationship_type",
        "content_tagged_relationship_type",
        "content_object_type",
        "content_tag_object_type",
        "dismissed_relationship_type",
        "allow_missing_object",
        "limit",
    ],
    "get_related_tags": [
        "object",
        "content_object_type",
        "content_tagged_relationship_type",
        "disregard_tag_ids",
    ],
    "get_related_content": [
        "object",
        "content_tagged_relationship_type",
        "content_tagged_object_type",
        "positive_rel",
        "actor_object_type",
    ],
    "get_related_users": [
        "object",
        "followed_relationship_type",
        "content_tagged_relationship_type",
        "content_tagged_object_type",
        "content_object_type",
        "content_published_relationship_type",
    ],
    "get_relationship_counts": ["object", "relationships"],
    "get_relationship_exists": ["object", "relationship_type", "end_object"],
}
JSON_FIELDS = {
    "create_event": ["event"],
    "delete_event": ["event"],
    "create_events_batch": ["events"],
    "get_object": ["object"],
    "delete_object": ["object"],
    "edit_object": ["object", "new_props"],
    "get_activity_on_object": ["object", "relationship_types"],
    "get_activity_feed": [
        "object",
        "follow_relationship_types",
        "follow_object_types",
        "event_relationship_types",
        "event_object_types",
    ],
    "get_activity_actions_feed": [
        "object",
        "follow_relationship_types",
        "follow_object_types",
        "event_relationship_types",
        "event_object_types",
    ],
    "get_recent_events": [],
    "get_recommended_content": ["object", "coldstart_tag_ids", "filter_tag_ids"],
    "get_sorted_content": ["object", "content_ids"],
    "get_recommended_users_to_follow": ["object"],
    "get_related_tags": ["object", "disregard_tag_ids"],
    "get_related_content": ["object"],
    "get_related_users": ["object"],
    "get_relationship_counts": ["object", "relationships"],
    "get_relationship_exists": ["object", "end_object"],
}


class PipelessNode(WorkflowNode):
    integration_type = "automation-pipeless"
    connection_evidence = ConnectionEvidence(
        noun="Pipeless app events", operation="get_recent_events", label_keys=("name",)
    )

    @classmethod
    def get_config_model(cls):
        return PipelessFullConfig

    async def execute(self, input_data):
        if not self.config.credentials:
            raise ValueError("Connect a Pipeless app API key")
        config, credential = self.config.config, self.config.credentials
        method, path, statuses = ROUTES[config.operation]
        path = path.replace("{app_id}", credential.app_id)
        values = config.model_dump(exclude_none=True)
        body = {
            key: values[key] for key in BODY_FIELDS[config.operation] if key in values
        }
        for key in JSON_FIELDS[config.operation]:
            if key in body:
                body[key] = json.loads(body[key])
        if (
            config.operation == "create_events_batch"
            and not 1 <= len(body["events"]) <= 10
        ):
            raise ValueError("Send between 1 and 10 events in one batch")
        if (
            config.operation == "get_relationship_counts"
            and not 1 <= len(body["relationships"]) <= 2
        ):
            raise ValueError("Count one or two relationships per request")
        try:
            async with guarded_async_client(
                timeout=30, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.request(
                    method,
                    "https://api.pipeless.io" + path,
                    headers={
                        "Authorization": "Bearer " + credential.api_key,
                        "Accept": "application/json",
                    },
                    json=body,
                )
        except httpx.RequestError:
            raise ValueError(
                "Pipeless request could not be completed; check writes before retrying"
            ) from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Pipeless returned an unreadable JSON response") from None
        if (
            response.status_code not in statuses
            or isinstance(payload, dict)
            and "errors" in payload
        ):
            message = payload.get("errors") if isinstance(payload, dict) else None
            return {
                "status": "error",
                "http_status": response.status_code,
                "error": _redact(
                    "; ".join(map(str, message))
                    if isinstance(message, list)
                    else "Pipeless rejected the request",
                    credential.api_key,
                ),
            }
        if not isinstance(payload, (dict, list)):
            raise ValueError("Pipeless returned an unexpected response shape")
        if config.operation == "get_recent_events" and not isinstance(payload, list):
            raise ValueError("Pipeless returned an unexpected recent events list")
        output = {
            "status": "success",
            "http_status": response.status_code,
            "data": _redact(payload, credential.api_key),
        }
        if response.status_code == 202:
            output["accepted"] = True
            output["completed"] = False
        if config.operation == "get_recent_events":
            output["items"] = _redact(
                [{"name": _event_name(row)} for row in payload], credential.api_key
            )
        return output


def _event_name(row):
    if not isinstance(row, dict) or not isinstance(row.get("event"), dict):
        raise ValueError("Pipeless returned an invalid recent event")
    event = row["event"]
    start, rel, end = (
        event.get(key) for key in ("start_object", "relationship", "end_object")
    )
    if not all(isinstance(value, dict) for value in (start, rel, end)):
        raise ValueError("Pipeless returned an invalid recent event")
    return f"{start.get('id', '?')} {rel.get('type', '?')} {end.get('id', '?')}"


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value
