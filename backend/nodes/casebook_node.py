"""Casebook REST API: fixed JSON:API operations against the published Postman collection.

Manual Bearer tokens expire after one hour. Each operation makes one request;
list operations return the server's first page and preserve links/meta without
following URLs. No automatic mutation retries or token exchanges.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.casebook.net"
MEDIA_TYPE = "application/vnd.api+json"


class CasebookBearerTokenCredential(BaseModel):
    model_config = ConfigDict(title="Casebook Bearer Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://gohub.casebook.net/knowledge/obtain-a-bearer-token",
            "x-credential-instructions": "Register an incoming application in Casebook Admin > Global > Integrations and obtain a Bearer token using Casebook's documented client credentials request. Paste the access_token without the Bearer prefix. Tokens expire after one hour: replace the token before running again. NoClick does not refresh it. Requires External Data Interoperability licensing and application roles for each operation. This integration uses the US API (api.casebook.net).",
        })
    credential_type: Literal["casebook_bearer_token"] = Field("casebook_bearer_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=8192, title="Bearer token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Bearer token", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the access token without the Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Resource(_Input):
    record_id: UUID = Field(..., title="Record ID", description="UUID of the record in Casebook.")


class _List(_Input):
    """Return the server's first page, preserving its links and metadata.

    The pinned collection disables all query parameters; this initial integration
    intentionally sends none. It never follows a server-provided link.
    """


class CasebookCaseList(_List):
    """List cases (first page only)."""
    operation: Literal["list_cases"] = Field("list_cases", title="List Cases", json_schema_extra={"ui:hidden": True})


class CasebookCaseGet(_Resource):
    """Get case."""
    operation: Literal["get_case"] = Field("get_case", title="Get Case", json_schema_extra={"ui:hidden": True})


class CasebookCaseCreate(_Input):
    """Create case."""
    operation: Literal["create_case"] = Field("create_case", title="Create Case", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=100000)
    description: str | None = Field(None, min_length=1, max_length=100000)
    goals: str | None = Field(None, min_length=1, max_length=100000)
    legacy_id: str | None = Field(None, min_length=1, max_length=100000)
    case_status_id: UUID | None = Field(None)
    case_type_id: UUID | None = Field(None)


class CasebookCaseUpdate(_Resource):
    """Update case."""
    operation: Literal["update_case"] = Field("update_case", title="Update Case", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, max_length=100000)
    description: str | None = Field(None, min_length=1, max_length=100000)
    goals: str | None = Field(None, min_length=1, max_length=100000)
    legacy_id: str | None = Field(None, min_length=1, max_length=100000)
    case_status_id: UUID | None = Field(None)
    case_type_id: UUID | None = Field(None)

    @model_validator(mode="after")
    def nonempty_patch(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "record_id"}):
            raise ValueError("Supply at least one field to update")
        return self


class CasebookPersonList(_List):
    """List people (first page only)."""
    operation: Literal["list_people"] = Field("list_people", title="List People", json_schema_extra={"ui:hidden": True})


class CasebookPersonGet(_Resource):
    """Get person."""
    operation: Literal["get_person"] = Field("get_person", title="Get Person", json_schema_extra={"ui:hidden": True})


class CasebookPersonCreate(_Input):
    """Create person."""
    operation: Literal["create_person"] = Field("create_person", title="Create Person", json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., min_length=1, max_length=100000)
    last_name: str = Field(..., min_length=1, max_length=100000)
    middle_name: str | None = Field(None, min_length=1, max_length=100000)
    preferred_name: str | None = Field(None, min_length=1, max_length=100000)
    date_of_birth: date | None = Field(None)
    legacy_id: str | None = Field(None, min_length=1, max_length=100000)


class CasebookPersonUpdate(_Resource):
    """Update person."""
    operation: Literal["update_person"] = Field("update_person", title="Update Person", json_schema_extra={"ui:hidden": True})
    first_name: str | None = Field(None, min_length=1, max_length=100000)
    last_name: str | None = Field(None, min_length=1, max_length=100000)
    middle_name: str | None = Field(None, min_length=1, max_length=100000)
    preferred_name: str | None = Field(None, min_length=1, max_length=100000)
    date_of_birth: date | None = Field(None)
    legacy_id: str | None = Field(None, min_length=1, max_length=100000)

    @model_validator(mode="after")
    def nonempty_patch(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "record_id"}):
            raise ValueError("Supply at least one field to update")
        return self


class CasebookIntakeReportList(_List):
    """List intake reports (first page only)."""
    operation: Literal["list_intake_reports"] = Field("list_intake_reports", title="List Intake Reports", json_schema_extra={"ui:hidden": True})


class CasebookIntakeReportGet(_Resource):
    """Get intake report."""
    operation: Literal["get_intake_report"] = Field("get_intake_report", title="Get Intake Report", json_schema_extra={"ui:hidden": True})


class CasebookIntakeReportCreate(_Input):
    """Create intake report."""
    operation: Literal["create_intake_report"] = Field("create_intake_report", title="Create Intake Report", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=100000)
    narrative: str | None = Field(None, min_length=1, max_length=100000)
    referred_by: str | None = Field(None, min_length=1, max_length=100000)
    decision_notes: str | None = Field(None, min_length=1, max_length=100000)
    report_type_id: UUID | None = Field(None)
    report_status_id: UUID | None = Field(None)


class CasebookIntakeReportUpdate(_Resource):
    """Update intake report."""
    operation: Literal["update_intake_report"] = Field("update_intake_report", title="Update Intake Report", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, max_length=100000)
    narrative: str | None = Field(None, min_length=1, max_length=100000)
    referred_by: str | None = Field(None, min_length=1, max_length=100000)
    decision_notes: str | None = Field(None, min_length=1, max_length=100000)
    report_type_id: UUID | None = Field(None)
    report_status_id: UUID | None = Field(None)

    @model_validator(mode="after")
    def nonempty_patch(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "record_id"}):
            raise ValueError("Supply at least one field to update")
        return self


class CasebookNoteList(_List):
    """List notes (first page only)."""
    operation: Literal["list_notes"] = Field("list_notes", title="List Notes", json_schema_extra={"ui:hidden": True})


class CasebookNoteGet(_Resource):
    """Get note."""
    operation: Literal["get_note"] = Field("get_note", title="Get Note", json_schema_extra={"ui:hidden": True})


class CasebookNoteCreate(_Input):
    """Create note."""
    operation: Literal["create_note"] = Field("create_note", title="Create Note", json_schema_extra={"ui:hidden": True})
    narrative: str = Field(..., min_length=1, max_length=100000)
    description: str | None = Field(None, min_length=1, max_length=100000)
    author: str | None = Field(None, min_length=1, max_length=100000)
    resource_id: UUID = Field(...)
    resource_type: str = Field(..., min_length=1, max_length=100000)
    namespace: str = Field(..., min_length=1, max_length=100000)
    note_type_id: UUID | None = Field(None)


class CasebookNoteUpdate(_Resource):
    """Update note."""
    operation: Literal["update_note"] = Field("update_note", title="Update Note", json_schema_extra={"ui:hidden": True})
    narrative: str | None = Field(None, min_length=1, max_length=100000)
    description: str | None = Field(None, min_length=1, max_length=100000)
    author: str | None = Field(None, min_length=1, max_length=100000)
    resource_id: UUID | None = Field(None)
    resource_type: str | None = Field(None, min_length=1, max_length=100000)
    namespace: str | None = Field(None, min_length=1, max_length=100000)
    note_type_id: UUID | None = Field(None)

    @model_validator(mode="after")
    def nonempty_patch(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "record_id"}):
            raise ValueError("Supply at least one field to update")
        return self


class CasebookServiceEnrollmentList(_List):
    """List service enrollments (first page only)."""
    operation: Literal["list_service_enrollments"] = Field("list_service_enrollments", title="List Service Enrollments", json_schema_extra={"ui:hidden": True})


class CasebookServiceEnrollmentGet(_Resource):
    """Get service enrollment."""
    operation: Literal["get_service_enrollment"] = Field("get_service_enrollment", title="Get Service Enrollment", json_schema_extra={"ui:hidden": True})


class CasebookServiceEnrollmentCreate(_Input):
    """Create service enrollment."""
    operation: Literal["create_service_enrollment"] = Field("create_service_enrollment", title="Create Service Enrollment", json_schema_extra={"ui:hidden": True})
    person_id: UUID = Field(...)
    started_at: date | None = Field(None)
    ended_at: date | None = Field(None)
    ended: bool | None = Field(None)
    goals: str | None = Field(None, min_length=1, max_length=100000)
    notes: str | None = Field(None, min_length=1, max_length=100000)
    service_id: UUID = Field(...)


class CasebookServiceEnrollmentUpdate(_Resource):
    """Update service enrollment."""
    operation: Literal["update_service_enrollment"] = Field("update_service_enrollment", title="Update Service Enrollment", json_schema_extra={"ui:hidden": True})
    person_id: UUID | None = Field(None)
    started_at: date | None = Field(None)
    ended_at: date | None = Field(None)
    ended: bool | None = Field(None)
    goals: str | None = Field(None, min_length=1, max_length=100000)
    notes: str | None = Field(None, min_length=1, max_length=100000)
    service_id: UUID | None = Field(None)

    @model_validator(mode="after")
    def nonempty_patch(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "record_id"}):
            raise ValueError("Supply at least one field to update")
        return self


class CasebookListCaseStatus(_List):
    """List case statuss (first page only)."""
    operation: Literal["list_case_statuses"] = Field("list_case_statuses", json_schema_extra={"ui:hidden": True})


class CasebookListCaseType(_List):
    """List case types (first page only)."""
    operation: Literal["list_case_types"] = Field("list_case_types", json_schema_extra={"ui:hidden": True})


class CasebookListServiceOffering(_List):
    """List service offerings (first page only)."""
    operation: Literal["list_service_offerings"] = Field("list_service_offerings", json_schema_extra={"ui:hidden": True})


class CasebookListProvider(_List):
    """List providers (first page only)."""
    operation: Literal["list_providers"] = Field("list_providers", json_schema_extra={"ui:hidden": True})


CasebookConfig = Annotated[Union[
    CasebookCaseList,
    CasebookCaseGet,
    CasebookCaseCreate,
    CasebookCaseUpdate,
    CasebookPersonList,
    CasebookPersonGet,
    CasebookPersonCreate,
    CasebookPersonUpdate,
    CasebookIntakeReportList,
    CasebookIntakeReportGet,
    CasebookIntakeReportCreate,
    CasebookIntakeReportUpdate,
    CasebookNoteList,
    CasebookNoteGet,
    CasebookNoteCreate,
    CasebookNoteUpdate,
    CasebookServiceEnrollmentList,
    CasebookServiceEnrollmentGet,
    CasebookServiceEnrollmentCreate,
    CasebookServiceEnrollmentUpdate,
    CasebookListCaseStatus,
    CasebookListCaseType,
    CasebookListServiceOffering,
    CasebookListProvider,
], Field(discriminator="operation")]


class CasebookFullConfig(NodeConfig[CasebookConfig, CasebookBearerTokenCredential]):
    pass


OPERATIONS = {'list_cases': ('GET', '/cases/cases', 'cases', 'list'),
 'get_case': ('GET', '/cases/cases/{record_id}', 'cases', 'get'),
 'create_case': ('POST', '/cases/cases', 'cases', 'create'),
 'update_case': ('PATCH', '/cases/cases/{record_id}', 'cases', 'update'),
 'list_people': ('GET', '/people/people', 'people', 'list'),
 'get_person': ('GET', '/people/people/{record_id}', 'people', 'get'),
 'create_person': ('POST', '/people/people', 'people', 'create'),
 'update_person': ('PATCH', '/people/people/{record_id}', 'people', 'update'),
 'list_intake_reports': ('GET', '/intake/reports', 'reports', 'list'),
 'get_intake_report': ('GET', '/intake/reports/{record_id}', 'reports', 'get'),
 'create_intake_report': ('POST', '/intake/reports', 'reports', 'create'),
 'update_intake_report': ('PATCH', '/intake/reports/{record_id}', 'reports', 'update'),
 'list_notes': ('GET', '/attachments/notes', 'notes', 'list'),
 'get_note': ('GET', '/attachments/notes/{record_id}', 'notes', 'get'),
 'create_note': ('POST', '/attachments/notes', 'notes', 'create'),
 'update_note': ('PATCH', '/attachments/notes/{record_id}', 'notes', 'update'),
 'list_service_enrollments': ('GET',
                              '/services/service_enrollments',
                              'service_enrollments',
                              'list'),
 'get_service_enrollment': ('GET',
                            '/services/service_enrollments/{record_id}',
                            'service_enrollments',
                            'get'),
 'create_service_enrollment': ('POST',
                               '/services/service_enrollments',
                               'service_enrollments',
                               'create'),
 'update_service_enrollment': ('PATCH',
                               '/services/service_enrollments/{record_id}',
                               'service_enrollments',
                               'update'),
 'list_case_statuses': ('GET', '/cases/case_statuses', 'case_statuses', 'list'),
 'list_case_types': ('GET', '/cases/case_types', 'case_types', 'list'),
 'list_service_offerings': ('GET', '/services/service_offerings', 'service_offerings', 'list'),
 'list_providers': ('GET', '/providers/providers', 'providers', 'list')}

WRITE_FIELDS = {'create_case': {'attributes': ['name', 'description', 'goals', 'legacy_id'],
                 'relationships': {'case_status_id': ('case_status', 'case_statuses'),
                                   'case_type_id': ('case_type', 'case_types')}},
 'update_case': {'attributes': ['name', 'description', 'goals', 'legacy_id'],
                 'relationships': {'case_status_id': ('case_status', 'case_statuses'),
                                   'case_type_id': ('case_type', 'case_types')}},
 'create_person': {'attributes': ['first_name',
                                  'last_name',
                                  'middle_name',
                                  'preferred_name',
                                  'date_of_birth',
                                  'legacy_id'],
                   'relationships': {}},
 'update_person': {'attributes': ['first_name',
                                  'last_name',
                                  'middle_name',
                                  'preferred_name',
                                  'date_of_birth',
                                  'legacy_id'],
                   'relationships': {}},
 'create_intake_report': {'attributes': ['name', 'narrative', 'referred_by', 'decision_notes'],
                          'relationships': {'report_type_id': ('report_type', 'report_types'),
                                            'report_status_id': ('report_status',
                                                                 'report_status')}},
 'update_intake_report': {'attributes': ['name', 'narrative', 'referred_by', 'decision_notes'],
                          'relationships': {'report_type_id': ('report_type', 'report_types'),
                                            'report_status_id': ('report_status',
                                                                 'report_status')}},
 'create_note': {'attributes': ['narrative',
                                'description',
                                'author',
                                'resource_id',
                                'resource_type',
                                'namespace'],
                 'relationships': {'note_type_id': ('note_type', 'note_types')}},
 'update_note': {'attributes': ['narrative',
                                'description',
                                'author',
                                'resource_id',
                                'resource_type',
                                'namespace'],
                 'relationships': {'note_type_id': ('note_type', 'note_types')}},
 'create_service_enrollment': {'attributes': ['person_id',
                                              'started_at',
                                              'ended_at',
                                              'ended',
                                              'goals',
                                              'notes'],
                               'relationships': {'service_id': ('service', 'services')}},
 'update_service_enrollment': {'attributes': ['person_id',
                                              'started_at',
                                              'ended_at',
                                              'ended',
                                              'goals',
                                              'notes'],
                               'relationships': {'service_id': ('service', 'services')}}}


def _resource(value, expected_type):
    # Preserve all documented attributes, including literal placeholders in the
    # collection's saved examples. Input IDs are still validated as UUIDs.
    return (isinstance(value, dict) and value.get("type") == expected_type
            and isinstance(value.get("id"), str) and bool(value["id"])
            and isinstance(value.get("attributes"), dict))


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class CasebookNode(WorkflowNode):
    integration_type = "automation-casebook"
    connection_evidence = ConnectionEvidence(noun="cases", operation="list_cases")

    @classmethod
    def get_config_model(cls):
        return CasebookFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Casebook Bearer token")
        config = self.config.config
        values = config.model_dump(mode="json", exclude_none=True)
        method, template, resource_type, action = OPERATIONS[config.operation]
        path = template.format(**values)
        body = None
        if action in {"create", "update"}:
            fields = WRITE_FIELDS[config.operation]
            data = {"type": resource_type, "attributes": {
                k: values[k] for k in fields["attributes"] if k in values}}
            relationships = {relation: {"data": {"type": typ, "id": values[field]}}
                for field, (relation, typ) in fields["relationships"].items() if field in values}
            if relationships:
                data["relationships"] = relationships
            body = {"data": data}
        token = credential.access_token
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + token, "Accept": MEDIA_TYPE, "Content-Type": MEDIA_TYPE},
                    **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            return {"status": "error", "error": "Casebook request did not complete; inspect Casebook before retrying a write."}
        expected = 201 if action == "create" else 200
        if response.status_code != expected:
            return {"status": "error", "http_status": response.status_code,
                "error": _redact(response.text, token)[:2000] or "Casebook did not confirm the operation"}
        try:
            payload = response.json()
        except ValueError:
            return {"status": "error", "error": "Casebook returned a non-JSON response"}
        if not isinstance(payload, dict) or payload.get("errors") or payload.get("error"):
            return {"status": "error", "error": "Casebook returned an unexpected error envelope"}
        if action == "list":
            valid = isinstance(payload.get("data"), list) and all(_resource(v, resource_type) for v in payload["data"])
        else:
            # GETs wrap the resource in data; saved POST/PATCH examples are bare.
            valid = _resource(payload.get("data", payload), resource_type)
        if not valid:
            return {"status": "error", "error": "Casebook returned an unexpected resource shape"}
        result = {**_redact(payload, token), "status": "success"}
        if config.operation == "list_cases":
            # The shared evidence reader uses flat option labels. Keep the raw
            # JSON:API page too, while showing case names instead of opaque IDs.
            result["options"] = [{"label": row["attributes"].get("name") or row["id"],
                                  "value": row["id"]} for row in result["data"]]
        return result
