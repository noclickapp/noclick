"""JobAdder v2 recruiting operations, pinned to the provider's OpenAPI contract.

https://api.jobadder.com/v2/openapi.json
Writes send one request and are never retried. Acknowledgement does not prove
downstream notifications or business outcomes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.oauth.jobadder_oauth import OAUTH_PROVIDER
from nodes.scopes.jobadder import JOBADDER_SCOPES
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.jobadder.com/v2"


class JobAdderOAuthCredential(BaseModel):
    model_config = ConfigDict(title="JobAdder OAuth", hide_input_in_errors=True,
        json_schema_extra={"x-credential-type": "oauth", "x-oauth-provider": "jobadder",
            "x-oauth-scopes": sorted(JOBADDER_SCOPES.declared_scopes()),
            "x-credential-url": "https://developers.jobadder.com/",
            "x-credential-instructions": "Sign in with JobAdder using a registered developer application. To connect manually, paste an existing OAuth access token; optionally provide its refresh token and ISO 8601 expiry. API keys are not supported."})
    credential_type: Literal["jobadder_oauth"] = Field("jobadder_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str | None = Field(None, title="Refresh token", repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = Field(None, title="Token expiry", description="ISO 8601 timestamp including timezone.")

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def secret(cls, value):
        return clean_secret(value, field_name="OAuth token") if value is not None else None

    @field_validator("expires_at")
    @classmethod
    def expiry(cls, value):
        if value is not None:
            try:
                if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise ValueError("Use an ISO 8601 expiry including timezone") from None
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, populate_by_name=True)

OPERATIONS = {'get_current_user': {'method': 'GET',
                      'path': '/users/current',
                      'query': {},
                      'body': {},
                      'status': [200],
                      'id': 'GetCurrentUser'},
 'list_candidates': {'method': 'GET',
                     'path': '/candidates',
                     'query': {'offset': 'Offset',
                               'limit': 'Limit',
                               'first_name': 'FirstName',
                               'last_name': 'LastName',
                               'email': 'Email'},
                     'body': {},
                     'status': [200],
                     'id': 'FindCandidates'},
 'get_candidate': {'method': 'GET',
                   'path': '/candidates/{candidateId}',
                   'query': {},
                   'body': {},
                   'status': [200],
                   'id': 'GetCandidate'},
 'create_candidate': {'method': 'POST',
                      'path': '/candidates',
                      'query': {},
                      'body': {'first_name': 'firstName',
                               'last_name': 'lastName',
                               'email': 'email',
                               'phone': 'phone',
                               'mobile': 'mobile',
                               'summary': 'summary',
                               'status_id': 'statusId'},
                      'status': [201],
                      'id': 'AddCandidate'},
 'update_candidate': {'method': 'PUT',
                      'path': '/candidates/{candidateId}',
                      'query': {},
                      'body': {'first_name': 'firstName',
                               'last_name': 'lastName',
                               'email': 'email',
                               'phone': 'phone',
                               'mobile': 'mobile',
                               'summary': 'summary',
                               'status_id': 'statusId'},
                      'status': [200],
                      'id': 'UpdateCandidate'},
 'list_companies': {'method': 'GET',
                    'path': '/companies',
                    'query': {'offset': 'Offset', 'limit': 'Limit', 'name': 'Name'},
                    'body': {},
                    'status': [200],
                    'id': 'FindCompanies'},
 'get_company': {'method': 'GET',
                 'path': '/companies/{companyId}',
                 'query': {},
                 'body': {},
                 'status': [200],
                 'id': 'GetCompany'},
 'create_company': {'method': 'POST',
                    'path': '/companies',
                    'query': {},
                    'body': {'name': 'name',
                             'summary': 'summary',
                             'status_id': 'statusId',
                             'owner_user_id': 'ownerUserId'},
                    'status': [201],
                    'id': 'AddCompany'},
 'update_company': {'method': 'PUT',
                    'path': '/companies/{companyId}',
                    'query': {},
                    'body': {'name': 'name',
                             'summary': 'summary',
                             'status_id': 'statusId',
                             'owner_user_id': 'ownerUserId'},
                    'status': [200],
                    'id': 'UpdateCompany'},
 'list_contacts': {'method': 'GET',
                   'path': '/contacts',
                   'query': {'offset': 'Offset',
                             'limit': 'Limit',
                             'first_name': 'FirstName',
                             'last_name': 'LastName',
                             'email': 'Email'},
                   'body': {},
                   'status': [200],
                   'id': 'FindContacts'},
 'get_contact': {'method': 'GET',
                 'path': '/contacts/{contactId}',
                 'query': {},
                 'body': {},
                 'status': [200],
                 'id': 'GetContact'},
 'create_contact': {'method': 'POST',
                    'path': '/contacts',
                    'query': {},
                    'body': {'first_name': 'firstName',
                             'last_name': 'lastName',
                             'email': 'email',
                             'phone': 'phone',
                             'company_id': 'companyId',
                             'position': 'position',
                             'summary': 'summary',
                             'status_id': 'statusId'},
                    'status': [201],
                    'id': 'AddContact'},
 'update_contact': {'method': 'PUT',
                    'path': '/contacts/{contactId}',
                    'query': {},
                    'body': {'first_name': 'firstName',
                             'last_name': 'lastName',
                             'email': 'email',
                             'phone': 'phone',
                             'company_id': 'companyId',
                             'position': 'position',
                             'summary': 'summary',
                             'status_id': 'statusId'},
                    'status': [200],
                    'id': 'UpdateContact'},
 'list_jobs': {'method': 'GET',
               'path': '/jobs',
               'query': {'offset': 'Offset', 'limit': 'Limit', 'job_title': 'JobTitle'},
               'body': {},
               'status': [200],
               'id': 'FindJobOrders'},
 'get_job': {'method': 'GET',
             'path': '/jobs/{jobId}',
             'query': {},
             'body': {},
             'status': [200],
             'id': 'GetJobOrder'},
 'create_job': {'method': 'POST',
                'path': '/jobs',
                'query': {},
                'body': {'job_title': 'jobTitle',
                         'company_id': 'companyId',
                         'contact_id': 'contactId',
                         'job_description': 'jobDescription',
                         'status_id': 'statusId',
                         'owner_user_id': 'ownerUserId',
                         'number_of_jobs': 'numberOfJobs'},
                'status': [201],
                'id': 'AddJobOrder'},
 'update_job': {'method': 'PUT',
                'path': '/jobs/{jobId}',
                'query': {},
                'body': {'job_title': 'jobTitle',
                         'company_id': 'companyId',
                         'contact_id': 'contactId',
                         'job_description': 'jobDescription',
                         'status_id': 'statusId',
                         'owner_user_id': 'ownerUserId',
                         'number_of_jobs': 'numberOfJobs'},
                'status': [200],
                'id': 'UpdateJobOrder'},
 'list_placements': {'method': 'GET',
                     'path': '/placements',
                     'query': {'offset': 'Offset', 'limit': 'Limit'},
                     'body': {},
                     'status': [200],
                     'id': 'FindPlacements'},
 'get_placement': {'method': 'GET',
                   'path': '/placements/{placementId}',
                   'query': {},
                   'body': {},
                   'status': [200],
                   'id': 'GetPlacement'},
 'list_candidate_notes': {'method': 'GET',
                          'path': '/candidates/{candidateId}/notes',
                          'query': {'offset': 'Offset', 'limit': 'Limit'},
                          'body': {},
                          'status': [200],
                          'id': 'GetCandidateNotes'},
 'create_candidate_note': {'method': 'POST',
                           'path': '/candidates/{candidateId}/notes',
                           'query': {},
                           'body': {'text': 'text',
                                    'note_type': 'type',
                                    'reference': 'reference',
                                    'created_by_integration': 'createdByIntegration'},
                           'status': [201],
                           'id': 'AddCandidateNote'},
 'list_job_applications': {'method': 'GET',
                           'path': '/jobs/{jobId}/applications',
                           'query': {'offset': 'Offset', 'limit': 'Limit'},
                           'body': {},
                           'status': [200],
                           'id': 'GetJobOrderJobApplications'},
 'add_candidates_to_job': {'method': 'POST',
                           'path': '/jobs/{jobId}/applications',
                           'query': {},
                           'body': {'candidate_ids': 'candidateId', 'source': 'source'},
                           'status': [201],
                           'id': 'AddJobOrderCandidates'}}
BODY_FIELDS = {name: tuple(op["body"]) for name, op in OPERATIONS.items()}

class GetCurrentUser(_Input):
    operation: Literal["get_current_user"] = Field("get_current_user", title="Get Current User", json_schema_extra={"ui:hidden": True})

class ListCandidates(_Input):
    operation: Literal["list_candidates"] = Field("list_candidates", title="List Candidates", json_schema_extra={"ui:hidden": True})
    offset: int = Field(0, ge=0, le=2147483647, description="First result index; use next_offset from the previous page.")
    limit: int = Field(100, ge=1, le=1000, description="Maximum results in this page.")
    first_name: str | None = Field(None, title='First name')
    last_name: str | None = Field(None, title='Last name')
    email: str | None = Field(None, title='Email')

class GetCandidate(_Input):
    operation: Literal["get_candidate"] = Field("get_candidate", title="Get Candidate", json_schema_extra={"ui:hidden": True})
    candidate_id: int = Field(..., title='Candidate id', ge=1, le=2147483647)

class CreateCandidate(_Input):
    operation: Literal["create_candidate"] = Field("create_candidate", title="Create Candidate", json_schema_extra={"ui:hidden": True})
    first_name: str | None = Field(None, title='First name', max_length=50)
    last_name: str | None = Field(None, title='Last name', max_length=50)
    email: str | None = Field(None, title='Email', max_length=100)
    phone: str | None = Field(None, title='Phone', max_length=50)
    mobile: str | None = Field(None, title='Mobile', max_length=50)
    summary: str | None = Field(None, title='Summary')
    status_id: int | None = Field(None, title='Status id', ge=1, le=2147483647)

    @model_validator(mode="after")
    def nonempty_write(self):
        if not any(getattr(self, name) is not None for name in BODY_FIELDS[self.operation]):
            raise ValueError("Provide at least one field to write")
        return self

class UpdateCandidate(_Input):
    operation: Literal["update_candidate"] = Field("update_candidate", title="Update Candidate", json_schema_extra={"ui:hidden": True})
    candidate_id: int = Field(..., title='Candidate id', ge=1, le=2147483647)
    first_name: str | None = Field(None, title='First name', max_length=50)
    last_name: str | None = Field(None, title='Last name', max_length=50)
    email: str | None = Field(None, title='Email', max_length=100)
    phone: str | None = Field(None, title='Phone', max_length=50)
    mobile: str | None = Field(None, title='Mobile', max_length=50)
    summary: str | None = Field(None, title='Summary')
    status_id: int | None = Field(None, title='Status id', ge=1, le=2147483647)

    @model_validator(mode="after")
    def nonempty_write(self):
        if not any(getattr(self, name) is not None for name in BODY_FIELDS[self.operation]):
            raise ValueError("Provide at least one field to write")
        return self

class ListCompanies(_Input):
    operation: Literal["list_companies"] = Field("list_companies", title="List Companies", json_schema_extra={"ui:hidden": True})
    offset: int = Field(0, ge=0, le=2147483647, description="First result index; use next_offset from the previous page.")
    limit: int = Field(100, ge=1, le=1000, description="Maximum results in this page.")
    name: str | None = Field(None, title='Name')

class GetCompany(_Input):
    operation: Literal["get_company"] = Field("get_company", title="Get Company", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., title='Company id', ge=1, le=2147483647)

class CreateCompany(_Input):
    operation: Literal["create_company"] = Field("create_company", title="Create Company", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., title='Name', max_length=100, min_length=1)
    summary: str | None = Field(None, title='Summary')
    status_id: int | None = Field(None, title='Status id', ge=1, le=2147483647)
    owner_user_id: int | None = Field(None, title='Owner user id', ge=1, le=2147483647)

    @model_validator(mode="after")
    def nonempty_write(self):
        if not any(getattr(self, name) is not None for name in BODY_FIELDS[self.operation]):
            raise ValueError("Provide at least one field to write")
        return self

class UpdateCompany(_Input):
    operation: Literal["update_company"] = Field("update_company", title="Update Company", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., title='Company id', ge=1, le=2147483647)
    name: str = Field(..., title='Name', max_length=100, min_length=1)
    summary: str | None = Field(None, title='Summary')
    status_id: int | None = Field(None, title='Status id', ge=1, le=2147483647)
    owner_user_id: int | None = Field(None, title='Owner user id', ge=1, le=2147483647)

    @model_validator(mode="after")
    def nonempty_write(self):
        if not any(getattr(self, name) is not None for name in BODY_FIELDS[self.operation]):
            raise ValueError("Provide at least one field to write")
        return self

class ListContacts(_Input):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})
    offset: int = Field(0, ge=0, le=2147483647, description="First result index; use next_offset from the previous page.")
    limit: int = Field(100, ge=1, le=1000, description="Maximum results in this page.")
    first_name: str | None = Field(None, title='First name')
    last_name: str | None = Field(None, title='Last name')
    email: str | None = Field(None, title='Email')

class GetContact(_Input):
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., title='Contact id', ge=1, le=2147483647)

class CreateContact(_Input):
    operation: Literal["create_contact"] = Field("create_contact", title="Create Contact", json_schema_extra={"ui:hidden": True})
    first_name: str | None = Field(None, title='First name', max_length=50)
    last_name: str | None = Field(None, title='Last name', max_length=50)
    email: str | None = Field(None, title='Email', max_length=100)
    phone: str | None = Field(None, title='Phone', max_length=50)
    company_id: int | None = Field(None, title='Company id', ge=1, le=2147483647)
    position: str | None = Field(None, title='Position')
    summary: str | None = Field(None, title='Summary')
    status_id: int | None = Field(None, title='Status id', ge=1, le=2147483647)

    @model_validator(mode="after")
    def nonempty_write(self):
        if not any(getattr(self, name) is not None for name in BODY_FIELDS[self.operation]):
            raise ValueError("Provide at least one field to write")
        return self

class UpdateContact(_Input):
    operation: Literal["update_contact"] = Field("update_contact", title="Update Contact", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., title='Contact id', ge=1, le=2147483647)
    first_name: str | None = Field(None, title='First name', max_length=50)
    last_name: str | None = Field(None, title='Last name', max_length=50)
    email: str | None = Field(None, title='Email', max_length=100)
    phone: str | None = Field(None, title='Phone', max_length=50)
    company_id: int | None = Field(None, title='Company id', ge=1, le=2147483647)
    position: str | None = Field(None, title='Position')
    summary: str | None = Field(None, title='Summary')
    status_id: int | None = Field(None, title='Status id', ge=1, le=2147483647)

    @model_validator(mode="after")
    def nonempty_write(self):
        if not any(getattr(self, name) is not None for name in BODY_FIELDS[self.operation]):
            raise ValueError("Provide at least one field to write")
        return self

class ListJobs(_Input):
    operation: Literal["list_jobs"] = Field("list_jobs", title="List Jobs", json_schema_extra={"ui:hidden": True})
    offset: int = Field(0, ge=0, le=2147483647, description="First result index; use next_offset from the previous page.")
    limit: int = Field(100, ge=1, le=1000, description="Maximum results in this page.")
    job_title: str | None = Field(None, title='Job title')

class GetJob(_Input):
    operation: Literal["get_job"] = Field("get_job", title="Get Job", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., title='Job id', ge=1, le=2147483647)

class CreateJob(_Input):
    operation: Literal["create_job"] = Field("create_job", title="Create Job", json_schema_extra={"ui:hidden": True})
    job_title: str = Field(..., title='Job title', max_length=100, min_length=1)
    company_id: int | None = Field(None, title='Company id', ge=1, le=2147483647)
    contact_id: int | None = Field(None, title='Contact id', ge=1, le=2147483647)
    job_description: str | None = Field(None, title='Job description')
    status_id: int | None = Field(None, title='Status id', ge=1, le=2147483647)
    owner_user_id: int | None = Field(None, title='Owner user id', ge=1, le=2147483647)
    number_of_jobs: int | None = Field(None, title='Number of jobs', ge=1, le=2147483647)

    @model_validator(mode="after")
    def nonempty_write(self):
        if not any(getattr(self, name) is not None for name in BODY_FIELDS[self.operation]):
            raise ValueError("Provide at least one field to write")
        return self

class UpdateJob(_Input):
    operation: Literal["update_job"] = Field("update_job", title="Update Job", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., title='Job id', ge=1, le=2147483647)
    job_title: str = Field(..., title='Job title', max_length=100, min_length=1)
    company_id: int | None = Field(None, title='Company id', ge=1, le=2147483647)
    contact_id: int | None = Field(None, title='Contact id', ge=1, le=2147483647)
    job_description: str | None = Field(None, title='Job description')
    status_id: int | None = Field(None, title='Status id', ge=1, le=2147483647)
    owner_user_id: int | None = Field(None, title='Owner user id', ge=1, le=2147483647)
    number_of_jobs: int | None = Field(None, title='Number of jobs', ge=1, le=2147483647)

    @model_validator(mode="after")
    def nonempty_write(self):
        if not any(getattr(self, name) is not None for name in BODY_FIELDS[self.operation]):
            raise ValueError("Provide at least one field to write")
        return self

class ListPlacements(_Input):
    operation: Literal["list_placements"] = Field("list_placements", title="List Placements", json_schema_extra={"ui:hidden": True})
    offset: int = Field(0, ge=0, le=2147483647, description="First result index; use next_offset from the previous page.")
    limit: int = Field(100, ge=1, le=1000, description="Maximum results in this page.")

class GetPlacement(_Input):
    operation: Literal["get_placement"] = Field("get_placement", title="Get Placement", json_schema_extra={"ui:hidden": True})
    placement_id: int = Field(..., title='Placement id', ge=1, le=2147483647)

class ListCandidateNotes(_Input):
    operation: Literal["list_candidate_notes"] = Field("list_candidate_notes", title="List Candidate Notes", json_schema_extra={"ui:hidden": True})
    candidate_id: int = Field(..., title='Candidate id', ge=1, le=2147483647)
    offset: int = Field(0, ge=0, le=2147483647, description="First result index; use next_offset from the previous page.")
    limit: int = Field(100, ge=1, le=1000, description="Maximum results in this page.")

class CreateCandidateNote(_Input):
    operation: Literal["create_candidate_note"] = Field("create_candidate_note", title="Create Candidate Note", json_schema_extra={"ui:hidden": True})
    candidate_id: int = Field(..., title='Candidate id', ge=1, le=2147483647)
    text: str = Field(..., title='Text', max_length=65535, min_length=1)
    note_type: str | None = Field(None, title='Note type', max_length=50)
    reference: str | None = Field(None, title='Reference', max_length=200)
    created_by_integration: bool | None = Field(None, title='Created by integration')

    @model_validator(mode="after")
    def nonempty_write(self):
        if not any(getattr(self, name) is not None for name in BODY_FIELDS[self.operation]):
            raise ValueError("Provide at least one field to write")
        return self

class ListJobApplications(_Input):
    operation: Literal["list_job_applications"] = Field("list_job_applications", title="List Job Applications", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., title='Job id', ge=1, le=2147483647)
    offset: int = Field(0, ge=0, le=2147483647, description="First result index; use next_offset from the previous page.")
    limit: int = Field(100, ge=1, le=1000, description="Maximum results in this page.")

class AddCandidatesToJob(_Input):
    operation: Literal["add_candidates_to_job"] = Field("add_candidates_to_job", title="Add Candidates To Job", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., title='Job id', ge=1, le=2147483647)
    candidate_ids: list[int] = Field(..., title='Candidate ids', min_length=1, max_length=1000)
    source: str | None = Field(None, title='Source', max_length=100)

    @model_validator(mode="after")
    def nonempty_write(self):
        if not any(getattr(self, name) is not None for name in BODY_FIELDS[self.operation]):
            raise ValueError("Provide at least one field to write")
        return self

JobAdderConfig = Annotated[Union[GetCurrentUser, ListCandidates, GetCandidate, CreateCandidate, UpdateCandidate, ListCompanies, GetCompany, CreateCompany, UpdateCompany, ListContacts, GetContact, CreateContact, UpdateContact, ListJobs, GetJob, CreateJob, UpdateJob, ListPlacements, GetPlacement, ListCandidateNotes, CreateCandidateNote, ListJobApplications, AddCandidatesToJob], Field(discriminator="operation")]


class JobAdderFullConfig(NodeConfig[JobAdderConfig, JobAdderOAuthCredential]):
    pass


def _redact(value, credential):
    secrets = [credential.get(name) for name in ("access_token", "refresh_token") if credential.get(name)]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, dict):
        return {key: _redact(item, credential) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, credential) for item in value]
    return value


class JobAdderNode(WorkflowNode):
    integration_type = "automation-jobadder"
    scope_registry = JOBADDER_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_current_user", noun="JobAdder user",
        label_keys=("email", "accountName", "firstName", "userId"))

    @classmethod
    def get_config_model(cls):
        return JobAdderFullConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=OAUTH_PROVIDER.refresh, provider="jobadder")

    async def execute(self, inputs):
        if not isinstance(self.config, JobAdderFullConfig) or not self.config.credentials:
            raise ValueError("Connect a JobAdder OAuth account")
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        credential = self.config.credentials.model_dump(exclude_none=True)
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=credential, refresh=OAUTH_PROVIDER.refresh, provider="jobadder", caller_path="execute")
        self.config.credentials = JobAdderOAuthCredential.model_validate(credential)
        config = self.config.config
        op = OPERATIONS[config.operation]
        path = op["path"]
        for field, value in config.model_dump().items():
            # All route parameters are bounded integer IDs, never user-selected URLs.
            wire = "".join(word.title() if i else word for i, word in enumerate(field.split("_")))
            path = path.replace("{" + wire + "}", str(value))
        params = {wire: getattr(config, field) for field, wire in op["query"].items() if getattr(config, field) is not None}
        body = {wire: getattr(config, field) for field, wire in op["body"].items() if getattr(config, field) is not None} if op["body"] else None
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(op["method"], BASE_URL + path, params=params or None, json=body,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        if response.status_code not in op["status"]:
            message = "JobAdder request failed"
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = error.get("message") or error.get("error_description") or message
            except ValueError:
                pass
            return _redact({"status": "error", "http_status": response.status_code, "error": message,
                "write_outcome": "unverified" if op["method"] != "GET" else None}, credential)
        if len(response.content) > 10_000_000:
            raise ValueError("JobAdder response exceeds the JSON limit")
        if not response.content and op["method"] == "PUT":
            # Update endpoints explicitly document a bodyless 200 acknowledgement.
            return {"status": "success", "data": None, "http_status": response.status_code,
                "write_acknowledged": True, "readback_verified": False}
        payload = response.json() if response.content else None
        if not isinstance(payload, dict) or any(key in payload for key in ("error", "errors")):
            raise ValueError("JobAdder returned an unexpected response; inspect writes before retrying")
        result = {"status": "success", "data": payload, "http_status": response.status_code}
        if config.operation.startswith("list_"):
            items, total = payload.get("items"), payload.get("totalCount")
            # items is nullable in the provider contract for empty collections.
            items = [] if items is None and total == 0 else items
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ValueError("JobAdder returned an invalid collection")
            if type(total) is not int or total < 0 or len(items) > config.limit:
                raise ValueError("JobAdder returned invalid pagination")
            next_offset = config.offset + len(items)
            has_more = next_offset < total
            result.update(items=items, total_count=total, offset=config.offset,
                has_more=has_more, next_offset=next_offset if has_more and items else None,
                complete=not has_more)
        elif op["method"] == "GET":
            id_field = {"get_current_user": "userId", "get_candidate": "candidateId",
                "get_company": "companyId", "get_contact": "contactId", "get_job": "jobId",
                "get_placement": "placementId"}[config.operation]
            if type(payload.get(id_field)) is not int:
                raise ValueError("JobAdder returned an invalid resource ID")
            if config.operation != "get_current_user":
                field = config.operation.removeprefix("get_") + "_id"
                if payload[id_field] != getattr(config, field):
                    raise ValueError("JobAdder returned a different resource")
        else:
            result.update(write_acknowledged=True, readback_verified=False)
        return _redact(result, credential)
