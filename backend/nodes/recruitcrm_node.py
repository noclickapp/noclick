"""Recruit CRM public API v8.7.6: fixed native recruiting operations.

Contract: https://docs.recruitcrm.io/api/projects/cHJqOjMwNzgy/branches/main/export/reference/Public-API.v1.json
Pagination is explicit: list operations fetch one page; no provider URL is followed.
Writes are sent once. A transport failure leaves their outcome unverified.
"""
from typing import Annotated, Literal, Union
import re
import json
import httpx
from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.recruitcrm.io"
FAMILY = "recruitcrm_api_token"


def _slug(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}", value):
        raise ValueError("Enter a single Recruit CRM record slug")
    return value


Slug = Annotated[str, BeforeValidator(_slug), Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,199}$", max_length=200)]
Text = Annotated[str, Field(min_length=1, max_length=10000)]


class RecruitCRMTokenCredential(BaseModel):
    model_config = ConfigDict(title="Recruit CRM API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://help.recruitcrm.io/en/articles/4411980-recruit-crm-api-documentation",
            "x-credential-instructions": "The account owner can enable and copy the API token under Admin Settings > API. Public API access requires a Business plan or an eligible partnership. Paste the token alone; NoClick sends it as a Bearer header to api.recruitcrm.io."
        })
    credential_type: Literal["recruitcrm_api_token"] = Field("recruitcrm_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the Recruit CRM API token")
        value = clean_secret(value, field_name="API token", key=True)
        if not value or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the token alone, without the Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, description="Fetch one page, starting at 1.")
    limit: int = Field(25, ge=1, le=100, description="Records per page; maximum 100.")


class _SortedPage(_Page):
    sort_by: Literal["createdon", "updatedon"] = "updatedon"
    sort_order: Literal["asc", "desc"] = "desc"


class _Search(_Input):
    sort_by: Literal["createdon", "updatedon"] = "updatedon"
    sort_order: Literal["asc", "desc"] = "desc"
    exact_search: Literal["true", "false", "1", "0"] | None = None


class _Update(_Input):
    @model_validator(mode="after")
    def has_change(self):
        fields = self.model_dump(exclude_none=True, exclude={"operation", "candidate", "company", "contact", "job"})
        if not fields:
            raise ValueError("Supply at least one field to update")
        return self


def _op(value, title):
    return Field(value, title=title, json_schema_extra={"ui:hidden": True, "x-display-name": title})

class ListCandidates(_SortedPage):
    """List Candidates using the corresponding Recruit CRM endpoint."""
    operation: Literal["list_candidates"] = _op("list_candidates", "List Candidates")


class GetCandidate(_Input):
    """Get Candidate using the corresponding Recruit CRM endpoint."""
    operation: Literal["get_candidate"] = _op("get_candidate", "Get Candidate")
    candidate: Slug


class SearchCandidates(_Search):
    """Search Candidates using the corresponding Recruit CRM endpoint."""
    operation: Literal["search_candidates"] = _op("search_candidates", "Search Candidates")
    first_name: Text | None = None
    last_name: Text | None = None
    email: Text | None = None
    contact_number: Text | None = None


class CreateCandidate(_Input):
    """Create Candidate using the corresponding Recruit CRM endpoint."""
    operation: Literal["create_candidate"] = _op("create_candidate", "Create Candidate")
    first_name: Text
    last_name: Text | None = None
    email: Text | None = None
    contact_number: Text | None = None
    city: Text | None = None
    state: Text | None = None
    country: Text | None = None
    position: Text | None = None
    current_organization: Text | None = None
    skill: Text | None = None
    source: Text | None = None
    candidate_summary: Text | None = None
    owner_id: int | None = Field(None, ge=1)


class ListCompanies(_SortedPage):
    """List Companies using the corresponding Recruit CRM endpoint."""
    operation: Literal["list_companies"] = _op("list_companies", "List Companies")


class GetCompany(_Input):
    """Get Company using the corresponding Recruit CRM endpoint."""
    operation: Literal["get_company"] = _op("get_company", "Get Company")
    company: Slug


class SearchCompanies(_Search):
    """Search Companies using the corresponding Recruit CRM endpoint."""
    operation: Literal["search_companies"] = _op("search_companies", "Search Companies")
    company_name: Text | None = None
    website: Text | None = None


class CreateCompany(_Input):
    """Create Company using the corresponding Recruit CRM endpoint."""
    operation: Literal["create_company"] = _op("create_company", "Create Company")
    company_name: Text
    about_company: Text | None = None
    website: Text | None = None
    city: Text | None = None
    state: Text | None = None
    country: Text | None = None
    industry_id: int | None = Field(None, ge=1)
    owner_id: int | None = Field(None, ge=1)


class UpdateCompany(_Update):
    """Update Company using the corresponding Recruit CRM endpoint."""
    operation: Literal["update_company"] = _op("update_company", "Update Company")
    company: Slug
    company_name: Text
    about_company: Text | None = None
    website: Text | None = None
    city: Text | None = None
    state: Text | None = None
    country: Text | None = None
    industry_id: int | None = Field(None, ge=1)
    owner_id: int | None = Field(None, ge=1)


class ListContacts(_SortedPage):
    """List Contacts using the corresponding Recruit CRM endpoint."""
    operation: Literal["list_contacts"] = _op("list_contacts", "List Contacts")


class GetContact(_Input):
    """Get Contact using the corresponding Recruit CRM endpoint."""
    operation: Literal["get_contact"] = _op("get_contact", "Get Contact")
    contact: Slug


class SearchContacts(_Search):
    """Search Contacts using the corresponding Recruit CRM endpoint."""
    operation: Literal["search_contacts"] = _op("search_contacts", "Search Contacts")
    first_name: Text | None = None
    last_name: Text | None = None
    email: Text | None = None
    contact_number: Text | None = None


class CreateContact(_Input):
    """Create Contact using the corresponding Recruit CRM endpoint."""
    operation: Literal["create_contact"] = _op("create_contact", "Create Contact")
    first_name: Text
    last_name: Text
    email: Text | None = None
    contact_number: Text | None = None
    city: Text | None = None
    state: Text | None = None
    country: Text | None = None
    company_slug: Text | None = None
    designation: Text | None = None
    stage_id: int | None = Field(None, ge=1)
    owner_id: int | None = Field(None, ge=1)


class UpdateContact(_Update):
    """Update Contact using the corresponding Recruit CRM endpoint."""
    operation: Literal["update_contact"] = _op("update_contact", "Update Contact")
    contact: Slug
    first_name: Text | None = None
    last_name: Text | None = None
    email: Text | None = None
    contact_number: Text | None = None
    city: Text | None = None
    state: Text | None = None
    country: Text | None = None
    company_slug: Text | None = None
    designation: Text | None = None
    stage_id: int | None = Field(None, ge=1)
    owner_id: int | None = Field(None, ge=1)


class ListJobs(_SortedPage):
    """List Jobs using the corresponding Recruit CRM endpoint."""
    operation: Literal["list_jobs"] = _op("list_jobs", "List Jobs")


class GetJob(_Input):
    """Get Job using the corresponding Recruit CRM endpoint."""
    operation: Literal["get_job"] = _op("get_job", "Get Job")
    job: Slug


class SearchJobs(_Search):
    """Search Jobs using the corresponding Recruit CRM endpoint."""
    operation: Literal["search_jobs"] = _op("search_jobs", "Search Jobs")
    name: Text | None = None
    company_slug: Text | None = None
    job_status: Text | None = None
    city: Text | None = None


class AssignCandidate(_Input):
    """Assign Candidate using the corresponding Recruit CRM endpoint."""
    operation: Literal["assign_candidate"] = _op("assign_candidate", "Assign Candidate")
    candidate: Slug
    job_slug: Slug
    updated_by: int | None = Field(None, ge=1)


class GetHiringStage(_Input):
    """Get Hiring Stage using the corresponding Recruit CRM endpoint."""
    operation: Literal["get_hiring_stage"] = _op("get_hiring_stage", "Get Hiring Stage")
    candidate: Slug
    job: Slug


class UpdateHiringStage(_Input):
    """Update Hiring Stage using the corresponding Recruit CRM endpoint."""
    operation: Literal["update_hiring_stage"] = _op("update_hiring_stage", "Update Hiring Stage")
    candidate: Slug
    job: Slug
    status_id: int = Field(..., ge=1)
    remark: Text | None = None
    stage_date: AwareDatetime | None = Field(None, description="ISO-8601 stage timestamp.")
    updated_by: int | None = Field(None, ge=1)


class ListNotes(_Page):
    """List Notes using the corresponding Recruit CRM endpoint."""
    operation: Literal["list_notes"] = _op("list_notes", "List Notes")


class CreateNote(_Input):
    """Create Note using the corresponding Recruit CRM endpoint."""
    operation: Literal["create_note"] = _op("create_note", "Create Note")
    description: Text
    related_to: Slug
    related_to_type: Literal["candidate", "company", "contact", "job", "deal"]
    note_type_id: int | None = Field(None, ge=1)


class ListTasks(_Page):
    """List Tasks using the corresponding Recruit CRM endpoint."""
    operation: Literal["list_tasks"] = _op("list_tasks", "List Tasks")


class GetTask(_Input):
    """Get Task using the corresponding Recruit CRM endpoint."""
    operation: Literal["get_task"] = _op("get_task", "Get Task")
    task: int = Field(..., ge=1)


class CreateTask(_Input):
    """Create Task using the corresponding Recruit CRM endpoint."""
    operation: Literal["create_task"] = _op("create_task", "Create Task")
    title: Text
    reminder: Literal[-1, 0, 15, 30, 60, 1440]
    start_date: AwareDatetime = Field(..., description="ISO-8601 start date and time.")
    description: Text | None = None
    task_type_id: int | None = Field(None, ge=1)
    owner_id: int | None = Field(None, ge=1)


RecruitCRMOperation = Annotated[Union[
    ListCandidates,
    GetCandidate,
    SearchCandidates,
    CreateCandidate,
    ListCompanies,
    GetCompany,
    SearchCompanies,
    CreateCompany,
    UpdateCompany,
    ListContacts,
    GetContact,
    SearchContacts,
    CreateContact,
    UpdateContact,
    ListJobs,
    GetJob,
    SearchJobs,
    AssignCandidate,
    GetHiringStage,
    UpdateHiringStage,
    ListNotes,
    CreateNote,
    ListTasks,
    GetTask,
    CreateTask
], Field(discriminator="operation")]


class RecruitCRMConfig(NodeConfig[RecruitCRMOperation, RecruitCRMTokenCredential]):
    pass


# Each operation has exactly one provider method/path. No arbitrary requests.
ROUTES = {'list_candidates': ('GET', '/v1/candidates', 'json', ['page', 'limit', 'sort_by', 'sort_order']), 'get_candidate': ('GET', '/v1/candidates/{candidate}', 'json', []), 'search_candidates': ('GET', '/v1/candidates/search', 'json', ['first_name', 'last_name', 'email', 'contact_number', 'sort_by', 'sort_order', 'exact_search']), 'create_candidate': ('POST', '/v1/candidates', 'json', []), 'list_companies': ('GET', '/v1/companies', 'json', ['page', 'limit', 'sort_by', 'sort_order']), 'get_company': ('GET', '/v1/companies/{company}', 'json', []), 'search_companies': ('GET', '/v1/companies/search', 'json', ['company_name', 'website', 'sort_by', 'sort_order', 'exact_search']), 'create_company': ('POST', '/v1/companies', 'json', []), 'update_company': ('POST', '/v1/companies/{company}', 'json', []), 'list_contacts': ('GET', '/v1/contacts', 'json', ['page', 'limit', 'sort_by', 'sort_order']), 'get_contact': ('GET', '/v1/contacts/{contact}', 'json', []), 'search_contacts': ('GET', '/v1/contacts/search', 'json', ['first_name', 'last_name', 'email', 'contact_number', 'sort_by', 'sort_order', 'exact_search']), 'create_contact': ('POST', '/v1/contacts', 'json', []), 'update_contact': ('POST', '/v1/contacts/{contact}', 'json', []), 'list_jobs': ('GET', '/v1/jobs', 'json', ['page', 'limit', 'sort_by', 'sort_order']), 'get_job': ('GET', '/v1/jobs/{job}', 'json', []), 'search_jobs': ('GET', '/v1/jobs/search', 'json', ['name', 'company_slug', 'job_status', 'city', 'sort_by', 'sort_order', 'exact_search']), 'assign_candidate': ('POST', '/v1/candidates/{candidate}/assign', 'json', ['job_slug', 'updated_by']), 'get_hiring_stage': ('GET', '/v1/candidates/{candidate}/hiring-stages/{job}', 'json', []), 'update_hiring_stage': ('POST', '/v1/candidates/{candidate}/hiring-stages/{job}', 'json', []), 'list_notes': ('GET', '/v1/notes', 'json', ['page', 'limit']), 'create_note': ('POST', '/v1/notes', 'json', []), 'list_tasks': ('GET', '/v1/tasks', 'json', ['page', 'limit']), 'get_task': ('GET', '/v1/tasks/{task}', 'json', []), 'create_task': ('POST', '/v1/tasks', 'json', [])}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class RecruitCRMNode(WorkflowNode):
    integration_type = "automation-recruitcrm"
    connection_evidence = ConnectionEvidence(
        noun="candidates", operation="list_candidates", label_keys=("email", "first_name", "slug", "id"))

    @classmethod
    def get_config_model(cls):
        return RecruitCRMConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if isinstance(raw, dict) and "credential_type" in raw and raw["credential_type"] != FAMILY:
            raise ValueError("Connect a Recruit CRM API token")
        return TypeAdapter(RecruitCRMConfig).validate_python(runtime_config_view(config_data, RecruitCRMConfig))

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Recruit CRM API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, template, media, query_keys = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = template
        for key in re.findall(r"\{(\w+)\}", template):
            path = path.replace("{" + key + "}", str(values.pop(key)) if key == "task" else _slug(values.pop(key)))
        params = {key: values.pop(key) for key in query_keys if key in values}
        kwargs = {}
        if method == "POST" and values:
            kwargs["json"] = values
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        try:
            async with guarded_async_client(timeout=30.0, trust_env=False, follow_redirects=False) as client:
                async with client.stream(method, BASE + path, headers=headers, params=params, **kwargs) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 10 * 1024 * 1024:
                            raise ValueError("Recruit CRM response exceeds 10 MB; reduce the page size")
                    try:
                        payload = json.loads(raw)
                    except (ValueError, UnicodeError):
                        raise ValueError("Recruit CRM returned an unreadable response; verify the outcome before retrying a write") from None
                    if response.status_code not in {200, 201} or (isinstance(payload, dict) and (payload.get("error") or payload.get("success") is False)):
                        message = payload.get("errorMessage") or payload.get("message") if isinstance(payload, dict) else None
                        output = {"success": False, "status": "error", "http_status": response.status_code,
                                  "message": _redact(message, token) if isinstance(message, str) else "Recruit CRM rejected the request"}
                    else:
                        if not isinstance(payload, (dict, list)):
                            raise ValueError("Recruit CRM returned an unexpected JSON shape")
                        output = {"success": True, "status": "success", "data": _redact(payload, token), "http_status": response.status_code}
        except httpx.HTTPError:
            raise ValueError("Recruit CRM request did not complete; verify the outcome before retrying a write") from None
        await self.emit(output)
        return output
