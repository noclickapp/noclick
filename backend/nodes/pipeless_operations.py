"""Pipeless v1 input models derived from the pinned provider OpenAPI contract.

Source: https://dash.readme.com/api/v1/api-registry/g2bqoleu3riwx
"""
from datetime import datetime
from typing import Annotated, Literal, Optional
from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _timestamp(value):
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Use an ISO 8601 date and time") from None
    if "T" not in value:
        raise ValueError("Include the time after T")
    return value


Timestamp = Annotated[str, AfterValidator(_timestamp)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ObjectWriteable(_Model):
    id: str = Field(
        ...,
        min_length=1,
        max_length=40,
        description="The id of your object. The id can be a string (up to 40 characters) containing any number, alpha character, spaces, or the following special characters: @-!#%^&()/+=;:'\"?<>\\][{}.,",
    )
    type: Literal[
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
        description="The type of an object. Can be any one of our predefined types. Although it is flexible what object type you use, as a best practice, we suggest you pick the one that relates best to the data you are representing. Doing this also allows specific algos to automatically work with their default settings.",
    )
    created_on: Optional[Timestamp] = Field(
        None,
        description="An optional DateTime string in the format YYYY-MM-DDTHH:MM:SS in whatever timezone you use. If not set, and the object needs to be created, this value will be set to the current UTC time.",
    )
    modified_on: Optional[Timestamp] = Field(
        None,
        description="An optional DateTime string in the format YYYY-MM-DDTHH:MM:SS in whatever timezone you use. If not set, the value will be set to the same value as created_on.",
    )


class RelationshipWriteable(_Model):
    type: Literal[
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
    ] = Field(
        ...,
        description="The type of relationship for an event. Can be any one of our predefined types. Although it is flexible what relationship type you use, as a best practice, we suggest you pick the one that relates best to the data you are representing. Doing this also allows specific algos to automatically work with their default settings.",
    )
    created_on: Optional[Timestamp] = Field(
        None,
        description="An optional DateTime string in the format YYYY-MM-DDTHH:MM:SS in whatever timezone you use. If not set, and the relationship needs to be created, this value will be set to the current UTC time.",
    )
    single: Optional[bool] = Field(
        None,
        description="Whether the relationship can be duplicated or not. If single is true (default), then a relationship of each type can only exist once between the same start and end objects. If false, a relationship of the same type can exist multiple times between the same start and end objects.",
    )


class CreateEventEvent(_Model):
    start_object: ObjectWriteable = Field(
        ...,
        description="An object to be written to your data. Only one object can exist for each type + id combo. If any of your write patterns provide an object that doesn't exist, it will be created. If the object already exists, the existing object will be used in your write operation, and if created_on or modified_on differ from the values already associated with the object, those values will be updated.",
    )
    relationship: RelationshipWriteable = Field(
        ..., description="The relationship for your event."
    )
    end_object: ObjectWriteable = Field(
        ...,
        description="An object to be written to your data. Only one object can exist for each type + id combo. If any of your write patterns provide an object that doesn't exist, it will be created. If the object already exists, the existing object will be used in your write operation, and if created_on or modified_on differ from the values already associated with the object, those values will be updated.",
    )


class ObjectLookup(_Model):
    id: str = Field(
        ...,
        min_length=1,
        max_length=40,
        description="id of the object you want to fetch.",
    )
    type: Literal[
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
    ] = Field(..., description="type of the object you want to fetch.")


class DeleteEventEventRelationship(_Model):
    type: Literal[
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
    ] = Field(...)
    created_on: Optional[Timestamp] = Field(None)


class ObjectWildcardLookup(_Model):
    id: Optional[str] = Field(
        None,
        min_length=1,
        max_length=40,
        description="id of the object you want to delete",
    )
    type: Literal[
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
    ] = Field(..., description="type of the object you want to fetch.")
    all: Optional[bool] = Field(
        None,
        description="If you want to delete all the relationships from the start object to the specified end object type (of any id), set this value to true. If true, the end object of the event will match any object of the specified type. Default value is false, meaning a specific id is required.",
    )


class DeleteEventEvent(_Model):
    start_object: ObjectLookup = Field(...)
    relationship: DeleteEventEventRelationship = Field(
        ...,
        description="When specifying the relationship of the event(s) to delete, if you only specify a type, then all events starting at the start object and going to the end object of the specified type will be deleted. If a created_on datetime is specified too, then only events where the relationship matches the specified type and created_on will be deleted.",
    )
    end_object: ObjectWildcardLookup = Field(...)


class CreateEventsBatchEventsItem(_Model):
    start_object: ObjectWriteable = Field(...)
    relationship: RelationshipWriteable = Field(...)
    end_object: ObjectWriteable = Field(...)


class EditObjectNewProps(_Model):
    id: Optional[str] = Field(
        None,
        min_length=1,
        max_length=40,
        description="New id for the object. If not included, the current id will be kept.",
    )
    created_on: Optional[Timestamp] = Field(
        None,
        description="New created_on (in datetime format) for the object. If not included, the current value will be kept.",
    )
    modified_on: Optional[Timestamp] = Field(
        None,
        description="New modified_on (in datetime format) for the object. If not included, the current value will be kept.",
    )


class GetRelationshipCountsRelationshipsItem(_Model):
    type: Literal[
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
    ] = Field(...)
    direction: Literal["incoming", "outgoing"] = Field(...)
    other_object_type: Literal[
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
    ] = Field(...)
