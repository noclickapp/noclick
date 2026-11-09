"""Recruiterflow external API, pinned to the publisher's swagger.yml v0.0.1.

Each operation makes one request. List operations return one page; updates
replace only the supplied keys, including entire email/phone/tag collections.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.recruiterflow.com"
DOCS_URL = "https://recruiterflow.com/api"


class RecruiterflowApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Recruiterflow API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": DOCS_URL,
        "x-credential-instructions": "Paste your Recruiterflow account API key. NoClick sends it in the RF-Api-Key header to api.recruiterflow.com. Connecting reads the users in your account.",
    })
    credential_type: Literal["recruiterflow_api_key"] = Field("recruiterflow_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    current_page: int = Field(1, ge=1, title="Page", description="One-based page number. This operation reads one page only.")
    items_per_page: int = Field(10, ge=1, le=100, title="Items Per Page")


class _Candidate(_Input):
    candidate_id: int = Field(..., ge=1, title="Candidate ID")


class _Contact(_Input):
    contact_id: int = Field(..., ge=1, title="Contact ID")


class _Company(_Input):
    company_id: int = Field(..., ge=1, title="Company ID")


class _Job(_Input):
    job_id: int = Field(..., ge=1, title="Job ID")


class Email(_Input):
    email: str = Field(..., min_length=1, max_length=320, title="Email Address")
    is_primary: Literal[0, 1] = Field(1, title="Primary Email")


class Phone(_Input):
    phone_number: str = Field(..., min_length=1, max_length=100, title="Phone Number")
    type: int = Field(..., ge=1, title="Phone Type ID", description="Use a phone type ID from Recruiterflow.")


class _Profile(_Input):
    email: list[Email] | None = Field(None, title="Email Addresses", description="When supplied on an update, replaces all email addresses. An empty list clears them.")
    phone_number: list[Phone] | None = Field(None, title="Phone Numbers", description="When supplied on an update, replaces all phone numbers. An empty list clears them.")
    title: str | None = Field(None, max_length=1000, title="Job Title")
    organization: str | None = Field(None, max_length=1000, title="Organization")
    linkedin_profile: str | None = Field(None, max_length=2000, title="LinkedIn Profile")
    tags: list[str] | None = Field(None, title="Tags", description="When supplied on an update, replaces the full tag list. An empty list clears it.")


class ListCandidates(_Page):
    operation: Literal["list_candidates"] = Field("list_candidates", title="List Candidates", json_schema_extra={"ui:hidden": True})


class GetCandidate(_Candidate):
    operation: Literal["get_candidate"] = Field("get_candidate", title="Get Candidate", json_schema_extra={"ui:hidden": True})


class CreateCandidate(_Profile):
    operation: Literal["create_candidate"] = Field("create_candidate", title="Create Candidate", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000, title="Name")
    source: str | None = Field(None, max_length=1000, title="Source")
    lead_owner_id: int | None = Field(None, ge=1, title="Lead Owner User ID")


class UpdateCandidate(_Candidate, _Profile):
    operation: Literal["update_candidate"] = Field("update_candidate", title="Update Candidate", description="Supplied keys replace their existing values. Omitted keys remain unchanged.", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, max_length=1000, title="Name")

    @model_validator(mode="after")
    def changes(self):
        if not any(k not in {"operation", "candidate_id"} and v is not None for k, v in self.model_dump().items()):
            raise ValueError("Supply at least one profile field to update")
        return self


class AddCandidateToJob(_Candidate, _Job):
    operation: Literal["add_candidate_to_job"] = Field("add_candidate_to_job", title="Add Candidate to Job", json_schema_extra={"ui:hidden": True})
    applied: Literal[0, 1] = Field(0, title="Applied", description="0 adds to Sourced; 1 adds as Applied and triggers Welcome Mail recipes.")
    added_time: str | None = Field(None, title="Added Time", description="Optional provider timestamp, e.g. 2021-01-12T10:16:16+0000.")


class MoveCandidateToStage(_Candidate, _Job):
    operation: Literal["move_candidate_to_stage"] = Field("move_candidate_to_stage", title="Move Candidate to Stage", json_schema_extra={"ui:hidden": True})
    stage_id: int = Field(..., ge=1, title="Destination Stage ID")
    user_id: int = Field(..., ge=1, title="Acting User ID")
    added_time: str | None = Field(None, title="Movement Time", description="Optional provider timestamp, e.g. 2021-01-12T10:16:16+0000.")


class AddCandidateNote(_Candidate):
    operation: Literal["add_candidate_note"] = Field("add_candidate_note", title="Add Candidate Note", json_schema_extra={"ui:hidden": True})
    value: str = Field(..., min_length=1, max_length=100000, title="Note", json_schema_extra={"ui:widget": "textarea"})
    created_by: int = Field(..., ge=1, title="Author User ID")
    mentions: list[int] | None = Field(None, title="Mentioned User IDs", description="Mentioning users can notify them in Recruiterflow.")


class ListContacts(_Page):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})


class GetContact(_Contact):
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})


class CreateContact(_Profile):
    operation: Literal["create_contact"] = Field("create_contact", title="Create Contact", json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., min_length=1, max_length=1000, title="First Name")
    last_name: str = Field(..., min_length=1, max_length=1000, title="Last Name")
    client_company: str | None = Field(None, max_length=1000, title="Client Company")
    source: str | None = Field(None, max_length=1000, title="Source")


class UpdateContact(_Contact, _Profile):
    operation: Literal["update_contact"] = Field("update_contact", title="Update Contact", description="Supplied keys replace their existing values. Omitted keys remain unchanged.", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, max_length=1000, title="Name")

    @model_validator(mode="after")
    def changes(self):
        if not any(k not in {"operation", "contact_id"} and v is not None for k, v in self.model_dump().items()):
            raise ValueError("Supply at least one profile field to update")
        return self


class ListCompanies(_Page):
    operation: Literal["list_companies"] = Field("list_companies", title="List Companies", json_schema_extra={"ui:hidden": True})


class GetCompany(_Company):
    operation: Literal["get_company"] = Field("get_company", title="Get Company", json_schema_extra={"ui:hidden": True})


class CreateCompany(_Input):
    operation: Literal["create_company"] = Field("create_company", title="Create Company", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000, title="Company Name")
    domain: str | None = Field(None, max_length=2000, title="Domain")
    phone_number: str | None = Field(None, max_length=100, title="Phone Number")
    lead_owner_id: int | None = Field(None, ge=1, title="Lead Owner User ID")
    status_id: int | None = Field(None, ge=1, title="Company Status ID")
    tags: list[str] | None = Field(None, title="Tags")


class ListJobs(_Page):
    operation: Literal["list_jobs"] = Field("list_jobs", title="List Jobs", json_schema_extra={"ui:hidden": True})
    only_open: Literal[0, 1] | None = Field(None, title="Only Open Jobs")


class GetJob(_Job):
    operation: Literal["get_job"] = Field("get_job", title="Get Job", json_schema_extra={"ui:hidden": True})
    include_stages: Literal[0, 1] = Field(1, title="Include Stages")


class GetJobPipeline(_Job):
    operation: Literal["get_job_pipeline"] = Field("get_job_pipeline", title="Get Job Pipeline", json_schema_extra={"ui:hidden": True})


class ListCampaigns(_Page):
    operation: Literal["list_campaigns"] = Field("list_campaigns", title="List Campaigns", json_schema_extra={"ui:hidden": True})


class _Campaign(_Input):
    campaign_id: int = Field(..., ge=1, title="Campaign ID")
    prospect_ids: list[int] = Field(..., min_length=1, title="Candidate or Contact IDs", description="Use prospects of the campaign's type.")

    @field_validator("prospect_ids")
    @classmethod
    def ids(cls, value):
        if any(i < 1 for i in value):
            raise ValueError("Prospect IDs must be positive integers")
        return value


class AddToCampaign(_Campaign):
    operation: Literal["add_to_campaign"] = Field("add_to_campaign", title="Add Prospects to Campaign", description="Enrolls candidates or contacts into an email campaign.", json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., ge=1, title="Acting User ID")


class RemoveFromCampaign(_Campaign):
    operation: Literal["remove_from_campaign"] = Field("remove_from_campaign", title="Remove Prospects from Campaign", json_schema_extra={"ui:hidden": True})


class ListUsers(_Input):
    operation: Literal["list_users"] = Field("list_users", title="List Users", json_schema_extra={"ui:hidden": True})


class ListTags(_Page):
    operation: Literal["list_tags"] = Field("list_tags", title="List Tags", json_schema_extra={"ui:hidden": True})


RecruiterflowOperation = Annotated[Union[
    ListCandidates, GetCandidate, CreateCandidate, UpdateCandidate, AddCandidateToJob,
    MoveCandidateToStage, AddCandidateNote, ListContacts, GetContact, CreateContact,
    UpdateContact, ListCompanies, GetCompany, CreateCompany, ListJobs, GetJob,
    GetJobPipeline, ListCampaigns, AddToCampaign, RemoveFromCampaign, ListUsers, ListTags,
], Field(discriminator="operation")]


class RecruiterflowNodeConfig(NodeConfig[RecruiterflowOperation, RecruiterflowApiKeyCredential]):
    pass


# Every entry is a single operation in https://recruiterflow.com/swagger.yml.
ROUTES = {
    "list_candidates": ("GET", "/api/external/candidate/list"),
    "get_candidate": ("GET", "/api/external/candidate/get"),
    "create_candidate": ("POST", "/api/external/candidate/add"),
    "update_candidate": ("POST", "/api/external/candidate/update"),
    "add_candidate_to_job": ("POST", "/api/external/candidate/add-to-job"),
    "move_candidate_to_stage": ("POST", "/api/external/candidate/move-to-stage"),
    "add_candidate_note": ("POST", "/api/external/candidate/notes/add"),
    "list_contacts": ("GET", "/api/external/contact/list"),
    "get_contact": ("GET", "/api/external/contact/get"),
    "create_contact": ("POST", "/api/external/contact/add"),
    "update_contact": ("POST", "/api/external/contact/update"),
    "list_companies": ("GET", "/api/external/client/list"),
    "get_company": ("GET", "/api/external/client/get"),
    "create_company": ("POST", "/api/external/client/add"),
    "list_jobs": ("GET", "/api/external/job/list"),
    "get_job": ("GET", "/api/external/job"),
    "get_job_pipeline": ("GET", "/api/external/job/pipeline"),
    "list_campaigns": ("GET", "/api/external/campaign/list"),
    "add_to_campaign": ("POST", "/api/external/campaign/add-to-campaign"),
    "remove_from_campaign": ("POST", "/api/external/campaign/remove-from-campaign"),
    "list_users": ("GET", "/api/external/user/list"),
    "list_tags": ("GET", "/api/external/tags/list"),
}


def request_fields(config):
    fields = config.model_dump(exclude={"operation"}, exclude_none=True)
    for name in ("candidate_id", "contact_id", "company_id", "prospect_ids"):
        if name in fields:
            fields["id"] = fields.pop(name)
    if "stage_id" in fields:
        fields["stage"] = {"id": fields.pop("stage_id")}
    return fields


def _error_message(payload, key):
    message = (payload.get("message") or payload.get("error")) if isinstance(payload, dict) else None
    if not isinstance(message, str):
        return "Recruiterflow rejected the request"
    return message.replace(key, "[redacted]")[:1000]


def _validate_payload(operation, payload):
    """A successful HTTP status alone never confirms a mutation."""
    def positive_id(value):
        return isinstance(value, dict) and type(value.get("id")) is int and value["id"] > 0

    if operation in {"create_candidate", "create_contact", "create_company"}:
        valid = isinstance(payload, dict) and positive_id(payload.get("data"))
        if operation != "create_company":
            valid = valid and payload.get("RESULT") == "SUCCESS"
    elif operation in {"update_candidate", "update_contact", "add_candidate_to_job", "move_candidate_to_stage", "remove_from_campaign"}:
        valid = isinstance(payload, dict) and payload.get("RESULT") == "SUCCESS"
    elif operation == "add_candidate_note":
        valid = isinstance(payload, dict) and type(payload.get("note_id")) is int and payload["note_id"] > 0
    elif operation == "add_to_campaign":
        valid = isinstance(payload, dict) and payload.get("data") == "SUCCESS"
    elif operation == "get_candidate":
        valid = isinstance(payload, list) and all(positive_id(row) for row in payload)
    elif operation in {"get_contact", "get_company", "get_job"}:
        valid = positive_id(payload)
    elif operation == "get_job_pipeline":
        valid = isinstance(payload, dict) and isinstance(payload.get("summary"), list) and isinstance(payload.get("detail"), list)
    else:
        valid = False
    if not valid:
        raise ValueError("Recruiterflow did not return the documented result; inspect the record before retrying a write")


class RecruiterflowNode(WorkflowNode):
    integration_type = "automation-recruiterflow"
    connection_evidence = ConnectionEvidence(noun="Recruiterflow users", operation="list_users")
    edit_examples = [
        "Create a Recruiterflow candidate from a form submission",
        "Move a candidate to an interview stage",
        "Add candidates to a Recruiterflow campaign",
        "List open Recruiterflow jobs",
    ]

    @classmethod
    def get_config_model(cls):
        return RecruiterflowNodeConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a Recruiterflow API key")
        method, path = ROUTES[config.operation]
        fields = request_fields(config)
        # The contract declares pagination as strings, IDs and flags as integers.
        if method == "GET":
            for name in ("current_page", "items_per_page"):
                if name in fields:
                    fields[name] = str(fields[name])
        headers = {"RF-Api-Key": credential.api_key, "Accept": "application/json"}
        kwargs = {"params": fields} if method == "GET" else {"json": fields}
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, **kwargs)
        try:
            payload = response.json()
        except (ValueError, UnicodeError):
            raise ValueError("Recruiterflow returned a non-JSON response") from None
        if response.status_code != 200 or (isinstance(payload, dict) and (
            str(payload.get("RESULT", "")).upper() == "FAILURE" or payload.get("error") or payload.get("success") is False
        )):
            return {"status": "error", "http_status": response.status_code, "error": _error_message(payload, credential.api_key)}
        if not isinstance(payload, (dict, list)):
            raise ValueError("Recruiterflow returned an unexpected JSON response")
        if config.operation.startswith("list_"):
            rows = payload if isinstance(payload, list) else payload.get("data")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("Recruiterflow returned an unexpected list response")
            return {"status": "success", "items": rows, "current_page": getattr(config, "current_page", None),
                    "items_per_page": getattr(config, "items_per_page", None),
                    "total_items": payload.get("total_items") if isinstance(payload, dict) else None}
        _validate_payload(config.operation, payload)
        return {"status": "success", "data": payload}
