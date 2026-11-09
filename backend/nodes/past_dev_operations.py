"""Typed past.dev Memory API operations, pinned to the published 1.0.0 contract.

Wire field names are retained in body/query models. Every operation makes one
request. Project selection comes only from the project API key.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


Text = Annotated[str, Field(min_length=1)]
IdentityID = Annotated[str, Field(min_length=1, max_length=200)]
TraitValue = Annotated[str, Field(min_length=1, max_length=2000)]
Traits = dict[IdentityID, TraitValue]


class IngestItem(Input):
    content: Text = Field(..., description="Source text, up to 16 MiB per request.")
    id: str | None = Field(None, description="Stable source ID without a slash. Omit to hash the content.")
    label: str | None = None
    timestamp: datetime | None = Field(None, description="Original occurrence time with a timezone.")
    metadata: Any = Field(None, description="Caller JSON stored with the source.", json_schema_extra={"ui:widget": "state_editor"})
    audience: str | None = Field(None, description="Omission makes the source project-visible, including on re-send.")
    identity: IdentityID | None = None

    @field_validator("content")
    @classmethod
    def content_present(cls, value):
        if not value.strip():
            raise ValueError("Source content cannot be blank")
        return value

    @field_validator("id")
    @classmethod
    def source_id(cls, value):
        if value is not None and (not value or "/" in value):
            raise ValueError("Source ID must be nonempty and contain no slash")
        return value

    @field_validator("timestamp")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Include the occurrence timezone")
        return value


class BulkIdentityRow(Input):
    identity: IdentityID
    traits: Traits = Field(default_factory=dict, json_schema_extra={"ui:widget": "state_editor"})


class AudienceCondition(Input):
    trait: IdentityID
    operator: Literal["is", "is_not", "is_one_of", "is_not_one_of", "exists", "does_not_exist"]
    values: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def value_count(self):
        count = len(self.values)
        if self.operator in {"is", "is_not"} and count != 1:
            raise ValueError("This operator needs exactly one value")
        if self.operator in {"is_one_of", "is_not_one_of"} and count < 1:
            raise ValueError("This operator needs at least one value")
        if self.operator in {"exists", "does_not_exist"} and count:
            raise ValueError("Existence operators take no values")
        return self


class AudienceRule(Input):
    match: Literal["all", "any"]
    conditions: list[AudienceCondition] = Field(..., min_length=1, max_length=20)


class Ingest(IngestItem):
    """Accept one data point."""
    operation: Literal["ingest"] = Field("ingest", title="Ingest", json_schema_extra={"ui:hidden": True})
    idempotencyKey: str | None = Field(None, max_length=200)

class IngestBatch(Input):
    """Accept an ordered batch."""
    operation: Literal["ingest_batch"] = Field("ingest_batch", title="Ingest Batch", json_schema_extra={"ui:hidden": True})
    items: list[IngestItem] = Field(..., min_length=1, max_length=1000, json_schema_extra={"ui:widget": "state_editor", "placeholder": "[]"})
    idempotencyKey: str | None = Field(None, max_length=200)

class GetIngestion(Input):
    """Read ingestion settlement."""
    operation: Literal["get_ingestion"] = Field("get_ingestion", title="Get Ingestion", json_schema_extra={"ui:hidden": True})
    ingestion_id: UUID = Field(...)

class DeleteIngestion(Input):
    """Forget an ingestion."""
    operation: Literal["delete_ingestion"] = Field("delete_ingestion", title="Delete Ingestion", json_schema_extra={"ui:hidden": True})
    ingestion_id: UUID = Field(...)

class Recall(Input):
    """Retrieve ranked memory documents."""
    operation: Literal["recall"] = Field("recall", title="Recall", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1)
    limit: int | None = Field(None, ge=1, le=200)
    level: Literal['low', 'medium', 'high', 'extra-high'] | None = Field(None)
    maxTokens: int | None = Field(None, ge=1)
    queryTimestamp: datetime | None = Field(None)
    occurredFrom: datetime | None = Field(None)
    occurredTo: datetime | None = Field(None)
    sort: Literal['relevance', 'chronological'] | None = Field(None)
    identity: str = Field(..., min_length=1, max_length=200)

    @model_validator(mode="after")
    def budget_and_range(self):
        if self.level is not None and self.maxTokens is not None:
            raise ValueError("Send level or maxTokens, never both")
        dates = (self.queryTimestamp, self.occurredFrom, self.occurredTo)
        if any(d is not None and d.tzinfo is None for d in dates):
            raise ValueError("Include the timezone in recall dates")
        if self.occurredFrom and self.occurredTo and self.occurredFrom > self.occurredTo:
            raise ValueError("The occurrence window starts after it ends")
        return self

class UpsertIdentity(Input):
    """Replace an identity."""
    operation: Literal["upsert_identity"] = Field("upsert_identity", title="Upsert Identity", json_schema_extra={"ui:hidden": True})
    identity: str = Field(..., min_length=1, max_length=200)
    traits: Traits = Field(default_factory=dict, json_schema_extra={"ui:widget": "state_editor"})

class PatchIdentity(Input):
    """Merge identity traits."""
    operation: Literal["patch_identity"] = Field("patch_identity", title="Patch Identity", json_schema_extra={"ui:hidden": True})
    identity: str = Field(..., min_length=1, max_length=200)
    traits: dict[IdentityID, TraitValue | None] = Field(default_factory=dict, json_schema_extra={"ui:widget": "state_editor"})

class GetIdentity(Input):
    """Read one identity."""
    operation: Literal["get_identity"] = Field("get_identity", title="Get Identity", json_schema_extra={"ui:hidden": True})
    identity: str = Field(..., min_length=1, max_length=200)

class DeleteIdentity(Input):
    """Delete one identity."""
    operation: Literal["delete_identity"] = Field("delete_identity", title="Delete Identity", json_schema_extra={"ui:hidden": True})
    identity: str = Field(..., min_length=1, max_length=200)

class BulkUpsertIdentities(Input):
    """Replace identities in bulk."""
    operation: Literal["bulk_upsert_identities"] = Field("bulk_upsert_identities", title="Bulk Upsert Identities", json_schema_extra={"ui:hidden": True})
    identities: list[BulkIdentityRow] = Field(..., min_length=1, max_length=1000, json_schema_extra={"ui:widget": "state_editor", "placeholder": "[]"})

class ListIdentities(Input):
    """List identities."""
    operation: Literal["list_identities"] = Field("list_identities", title="List Identities", json_schema_extra={"ui:hidden": True})
    after: str | None = None
    limit: int = Field(100, ge=1, le=1000)
    traitKey: str | None = None
    traitValue: str | None = None

class DeleteDataPoint(Input):
    """Delete one data point by source id."""
    operation: Literal["delete_data_point"] = Field("delete_data_point", title="Delete Data Point", json_schema_extra={"ui:hidden": True})
    source_id: str = Field(..., min_length=1)

class DeleteDataPoints(Input):
    """Delete data points by source id."""
    operation: Literal["delete_data_points"] = Field("delete_data_points", title="Delete Data Points", json_schema_extra={"ui:hidden": True})
    ids: list[Text] = Field(..., min_length=1, max_length=1000, json_schema_extra={"ui:widget": "state_editor", "placeholder": "[]"})

class ListAudiences(Input):
    """List audiences."""
    operation: Literal["list_audiences"] = Field("list_audiences", title="List Audiences", json_schema_extra={"ui:hidden": True})

class GetAudience(Input):
    """Read one audience."""
    operation: Literal["get_audience"] = Field("get_audience", title="Get Audience", json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., min_length=2, max_length=40, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")

class PutAudience(Input):
    """Create or replace an audience."""
    operation: Literal["put_audience"] = Field("put_audience", title="Put Audience", json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., min_length=2, max_length=40, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    kind: Literal['fixed', 'rule'] = Field(...)
    name: str | None = Field(None, min_length=1, max_length=200)
    identities: list[IdentityID] | None = Field(None, json_schema_extra={"ui:widget": "state_editor", "placeholder": "[]", "ui:show-if": {"kind": "fixed"}})
    rule: AudienceRule | None = Field(None, json_schema_extra={"ui:widget": "state_editor", "ui:show-if": {"kind": "rule"}})

    @model_validator(mode="after")
    def definition(self):
        if self.slug == "project":
            raise ValueError("The default audience cannot be replaced")
        if self.kind == "fixed" and (self.identities is None or self.rule is not None):
            raise ValueError("A fixed audience needs identities and no rule")
        if self.kind == "rule" and (self.rule is None or self.identities is not None):
            raise ValueError("A rule audience needs a rule and no identities")
        return self

class DeleteAudience(Input):
    """Delete an audience."""
    operation: Literal["delete_audience"] = Field("delete_audience", title="Delete Audience", json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., min_length=2, max_length=40, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")

    @field_validator("slug")
    @classmethod
    def mutable_slug(cls, value):
        if value == "project":
            raise ValueError("The default audience cannot be changed")
        return value

class RecomputeAudience(Input):
    """Recompute an audience."""
    operation: Literal["recompute_audience"] = Field("recompute_audience", title="Recompute Audience", json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., min_length=2, max_length=40, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")

    @field_validator("slug")
    @classmethod
    def mutable_slug(cls, value):
        if value == "project":
            raise ValueError("The default audience cannot be changed")
        return value

class RetryIngestion(Input):
    """Run a stopped send again."""
    operation: Literal["retry_ingestion"] = Field("retry_ingestion", title="Retry Ingestion", json_schema_extra={"ui:hidden": True})
    ingestion_id: UUID = Field(...)

class ExplainIngestion(Input):
    """Explain one send."""
    operation: Literal["explain_ingestion"] = Field("explain_ingestion", title="Explain Ingestion", json_schema_extra={"ui:hidden": True})
    ingestion_id: UUID = Field(...)

class GetUsage(Input):
    """Read this month's credits."""
    operation: Literal["get_usage"] = Field("get_usage", title="Get Usage", json_schema_extra={"ui:hidden": True})

Operation = Annotated[Union[Ingest, IngestBatch, GetIngestion, DeleteIngestion, Recall, UpsertIdentity, PatchIdentity, GetIdentity, DeleteIdentity, BulkUpsertIdentities, ListIdentities, DeleteDataPoint, DeleteDataPoints, ListAudiences, GetAudience, PutAudience, DeleteAudience, RecomputeAudience, RetryIngestion, ExplainIngestion, GetUsage], Field(discriminator="operation")]

OPERATIONS = {'ingest': {'method': 'POST',
            'path': '/api/v1/ingest',
            'path_fields': {},
            'query': {},
            'body': ['content',
                     'label',
                     'id',
                     'timestamp',
                     'metadata',
                     'audience',
                     'identity',
                     'idempotencyKey'],
            'array_body': False,
            'statuses': [200, 202]},
 'ingest_batch': {'method': 'POST',
                  'path': '/api/v1/ingest/batch',
                  'path_fields': {},
                  'query': {},
                  'body': ['items', 'idempotencyKey'],
                  'array_body': False,
                  'statuses': [200, 202]},
 'get_ingestion': {'method': 'GET',
                   'path': '/api/v1/ingest/{ingestionId}',
                   'path_fields': {'ingestion_id': 'ingestionId'},
                   'query': {},
                   'body': [],
                   'array_body': False,
                   'statuses': [200]},
 'delete_ingestion': {'method': 'DELETE',
                      'path': '/api/v1/ingest/{ingestionId}',
                      'path_fields': {'ingestion_id': 'ingestionId'},
                      'query': {},
                      'body': [],
                      'array_body': False,
                      'statuses': [204]},
 'recall': {'method': 'POST',
            'path': '/api/v1/recall',
            'path_fields': {},
            'query': {},
            'body': ['query',
                     'limit',
                     'level',
                     'maxTokens',
                     'queryTimestamp',
                     'occurredFrom',
                     'occurredTo',
                     'sort',
                     'identity'],
            'array_body': False,
            'statuses': [200]},
 'upsert_identity': {'method': 'PUT',
                     'path': '/api/v1/identities/{identity}',
                     'path_fields': {'identity': 'identity'},
                     'query': {},
                     'body': ['traits'],
                     'array_body': False,
                     'statuses': [200]},
 'patch_identity': {'method': 'PATCH',
                    'path': '/api/v1/identities/{identity}',
                    'path_fields': {'identity': 'identity'},
                    'query': {},
                    'body': ['traits'],
                    'array_body': False,
                    'statuses': [200]},
 'get_identity': {'method': 'GET',
                  'path': '/api/v1/identities/{identity}',
                  'path_fields': {'identity': 'identity'},
                  'query': {},
                  'body': [],
                  'array_body': False,
                  'statuses': [200]},
 'delete_identity': {'method': 'DELETE',
                     'path': '/api/v1/identities/{identity}',
                     'path_fields': {'identity': 'identity'},
                     'query': {},
                     'body': [],
                     'array_body': False,
                     'statuses': [204]},
 'bulk_upsert_identities': {'method': 'POST',
                            'path': '/api/v1/identities/bulk',
                            'path_fields': {},
                            'query': {},
                            'body': ['identities'],
                            'array_body': True,
                            'statuses': [200]},
 'list_identities': {'method': 'GET',
                     'path': '/api/v1/identities',
                     'path_fields': {},
                     'query': {'after': 'after',
                               'limit': 'limit',
                               'traitKey': 'traitKey',
                               'traitValue': 'traitValue'},
                     'body': [],
                     'array_body': False,
                     'statuses': [200]},
 'delete_data_point': {'method': 'DELETE',
                       'path': '/api/v1/data-points/{sourceId}',
                       'path_fields': {'source_id': 'sourceId'},
                       'query': {},
                       'body': [],
                       'array_body': False,
                       'statuses': [202]},
 'delete_data_points': {'method': 'POST',
                        'path': '/api/v1/data-points/delete',
                        'path_fields': {},
                        'query': {},
                        'body': ['ids'],
                        'array_body': False,
                        'statuses': [202]},
 'list_audiences': {'method': 'GET',
                    'path': '/api/v1/audiences',
                    'path_fields': {},
                    'query': {},
                    'body': [],
                    'array_body': False,
                    'statuses': [200]},
 'get_audience': {'method': 'GET',
                  'path': '/api/v1/audiences/{slug}',
                  'path_fields': {'slug': 'slug'},
                  'query': {},
                  'body': [],
                  'array_body': False,
                  'statuses': [200]},
 'put_audience': {'method': 'PUT',
                  'path': '/api/v1/audiences/{slug}',
                  'path_fields': {'slug': 'slug'},
                  'query': {},
                  'body': ['kind', 'name', 'identities', 'rule'],
                  'array_body': False,
                  'statuses': [200, 201]},
 'delete_audience': {'method': 'DELETE',
                     'path': '/api/v1/audiences/{slug}',
                     'path_fields': {'slug': 'slug'},
                     'query': {},
                     'body': [],
                     'array_body': False,
                     'statuses': [204]},
 'recompute_audience': {'method': 'POST',
                        'path': '/api/v1/audiences/{slug}/recompute',
                        'path_fields': {'slug': 'slug'},
                        'query': {},
                        'body': [],
                        'array_body': False,
                        'statuses': [200]},
 'retry_ingestion': {'method': 'POST',
                     'path': '/api/v1/ingest/{ingestionId}/retry',
                     'path_fields': {'ingestion_id': 'ingestionId'},
                     'query': {},
                     'body': [],
                     'array_body': False,
                     'statuses': [202]},
 'explain_ingestion': {'method': 'GET',
                       'path': '/api/v1/ingest/{ingestionId}/explain',
                       'path_fields': {'ingestion_id': 'ingestionId'},
                       'query': {},
                       'body': [],
                       'array_body': False,
                       'statuses': [200]},
 'get_usage': {'method': 'GET',
               'path': '/api/v1/usage',
               'path_fields': {},
               'query': {},
               'body': [],
               'array_body': False,
               'statuses': [200]}}
