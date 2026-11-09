"""Daylite personal-token CRM operations using the published v1 API.

Each operation makes one request and preserves the provider's JSON response.
Personal access tokens expire after one hour; users replace them after refreshing.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.marketcircle.net/v1"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class DaylitePersonalToken(_Model):
    model_config = ConfigDict(title="Daylite Personal Token", extra="forbid", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developer.daylite.app/reference/personal-token",
        "x-credential-instructions": "Generate a personal token in Daylite and paste its access_token. Tokens expire after one hour. Refresh it using Daylite's documented personal-token flow, then replace the access token here. Read and write operations require daylite:read and daylite:write respectively.",
    })
    credential_type: Literal["daylite_personal_token"] = Field("daylite_personal_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", min_length=1, max_length=8192, repr=False, description="Paste the access_token value, without the Bearer prefix. Personal access tokens expire after one hour.", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token")
    @classmethod
    def token(cls, value):
        value = value.strip()
        if not value or not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the access token, without spaces or the Bearer prefix")
        return value


class _Record(_Model):
    record_id: int = Field(..., gt=0, le=2147483647, title="Record ID", description="Numeric identifier from the record's self reference, for example 1000.")


class Email(_Model):
    label: str = Field(..., title="Label")
    address: str = Field(..., title="Email Address")


class _ContactFields(_Model):
    first_name: str | None = Field(None, title="First Name")
    last_name: str | None = Field(None, title="Last Name")
    category: str | None = Field(None, title="Category")
    keywords: list[str] | None = Field(None, title="Keywords")
    emails: list[Email] | None = Field(None, title="Emails")


class _CompanyFields(_Model):
    name: str | None = Field(None, title="Name")
    details: str | None = Field(None, title="Details", json_schema_extra={"ui:widget": "textarea"})
    category: str | None = Field(None, title="Category")
    keywords: list[str] | None = Field(None, title="Keywords")
    emails: list[Email] | None = Field(None, title="Emails")
    industry: str | None = Field(None, title="Industry")
    region: str | None = Field(None, title="Region")


class _TaskFields(_Model):
    title: str = Field(..., title="Title", min_length=1)
    details: str | None = Field(None, title="Details", json_schema_extra={"ui:widget": "textarea"})
    due: date | None = Field(None, title="Due Date")
    status: str | None = Field(None, title="Status", description="Daylite task status value; see the Task reference.")
    priority: str | None = Field(None, title="Priority", description="Daylite priority value; see the Task reference.")
    category: str | None = Field(None, title="Category")
    keywords: list[str] | None = Field(None, title="Keywords")


class _NoteFields(_Model):
    title: str | None = Field(None, title="Title")
    details: str | None = Field(None, title="Details", json_schema_extra={"ui:widget": "textarea"})
    category: str | None = Field(None, title="Category")
    keywords: list[str] | None = Field(None, title="Keywords")


class _ProjectFields(_Model):
    name: str | None = Field(None, title="Name")
    details: str | None = Field(None, title="Details", json_schema_extra={"ui:widget": "textarea"})
    status: str | None = Field(None, title="Status")
    due: date | None = Field(None, title="Due Date")
    priority: int | None = Field(None, ge=0, le=10, title="Priority")
    category: str | None = Field(None, title="Category")
    keywords: list[str] | None = Field(None, title="Keywords")


class _OpportunityFields(_Model):
    name: str | None = Field(None, title="Name")
    details: str | None = Field(None, title="Details", json_schema_extra={"ui:widget": "textarea"})
    state: str | None = Field(None, title="State")
    probability: int | None = Field(None, ge=0, le=100, title="Probability Percent")
    forecasted: date | None = Field(None, title="Expected Closing Date")
    priority: int | None = Field(None, ge=0, le=10, title="Priority")
    category: str | None = Field(None, title="Category")
    keywords: list[str] | None = Field(None, title="Keywords")


class ListContacts(_Model):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})
    include_trash: bool = Field(False, title="Include Trash")

class GetContact(_Record):
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})

class CreateContact(_ContactFields):
    operation: Literal["create_contact"] = Field("create_contact", title="Create Contact", json_schema_extra={"ui:hidden": True})

class UpdateContact(_Record, _ContactFields):
    operation: Literal["update_contact"] = Field("update_contact", title="Update Contact", json_schema_extra={"ui:hidden": True})

class ListCompanies(_Model):
    operation: Literal["list_companies"] = Field("list_companies", title="List Companies", json_schema_extra={"ui:hidden": True})
    include_trash: bool = Field(False, title="Include Trash")

class GetCompany(_Record):
    operation: Literal["get_company"] = Field("get_company", title="Get Company", json_schema_extra={"ui:hidden": True})

class CreateCompany(_CompanyFields):
    operation: Literal["create_company"] = Field("create_company", title="Create Company", json_schema_extra={"ui:hidden": True})

class UpdateCompany(_Record, _CompanyFields):
    operation: Literal["update_company"] = Field("update_company", title="Update Company", json_schema_extra={"ui:hidden": True})

class ListTasks(_Model):
    operation: Literal["list_tasks"] = Field("list_tasks", title="List Tasks", json_schema_extra={"ui:hidden": True})
    include_trash: bool = Field(False, title="Include Trash")

class GetTask(_Record):
    operation: Literal["get_task"] = Field("get_task", title="Get Task", json_schema_extra={"ui:hidden": True})

class CreateTask(_TaskFields):
    operation: Literal["create_task"] = Field("create_task", title="Create Task", json_schema_extra={"ui:hidden": True})

class UpdateTask(_Record, _TaskFields):
    operation: Literal["update_task"] = Field("update_task", title="Update Task", json_schema_extra={"ui:hidden": True})

class ListNotes(_Model):
    operation: Literal["list_notes"] = Field("list_notes", title="List Notes", json_schema_extra={"ui:hidden": True})
    include_trash: bool = Field(False, title="Include Trash")

class GetNote(_Record):
    operation: Literal["get_note"] = Field("get_note", title="Get Note", json_schema_extra={"ui:hidden": True})

class CreateNote(_NoteFields):
    operation: Literal["create_note"] = Field("create_note", title="Create Note", json_schema_extra={"ui:hidden": True})

class UpdateNote(_Record, _NoteFields):
    operation: Literal["update_note"] = Field("update_note", title="Update Note", json_schema_extra={"ui:hidden": True})

class ListProjects(_Model):
    operation: Literal["list_projects"] = Field("list_projects", title="List Projects", json_schema_extra={"ui:hidden": True})

class GetProject(_Record):
    operation: Literal["get_project"] = Field("get_project", title="Get Project", json_schema_extra={"ui:hidden": True})

class CreateProject(_ProjectFields):
    operation: Literal["create_project"] = Field("create_project", title="Create Project", json_schema_extra={"ui:hidden": True})

class UpdateProject(_Record, _ProjectFields):
    operation: Literal["update_project"] = Field("update_project", title="Update Project", json_schema_extra={"ui:hidden": True})

class ListOpportunities(_Model):
    operation: Literal["list_opportunities"] = Field("list_opportunities", title="List Opportunities", json_schema_extra={"ui:hidden": True})
    include_trash: bool = Field(False, title="Include Trash")

class GetOpportunity(_Record):
    operation: Literal["get_opportunity"] = Field("get_opportunity", title="Get Opportunity", json_schema_extra={"ui:hidden": True})

class CreateOpportunity(_OpportunityFields):
    operation: Literal["create_opportunity"] = Field("create_opportunity", title="Create Opportunity", json_schema_extra={"ui:hidden": True})

class UpdateOpportunity(_Record, _OpportunityFields):
    operation: Literal["update_opportunity"] = Field("update_opportunity", title="Update Opportunity", json_schema_extra={"ui:hidden": True})

class GetTokenMetadata(_Model):
    operation: Literal["get_token_metadata"] = Field("get_token_metadata", title="Get Token Metadata", json_schema_extra={"ui:hidden": True})

Operation = Annotated[Union[ListContacts, GetContact, CreateContact, UpdateContact, ListCompanies, GetCompany, CreateCompany, UpdateCompany, ListTasks, GetTask, CreateTask, UpdateTask, ListNotes, GetNote, CreateNote, UpdateNote, ListProjects, GetProject, CreateProject, UpdateProject, ListOpportunities, GetOpportunity, CreateOpportunity, UpdateOpportunity, GetTokenMetadata], Field(discriminator="operation")]

class DayliteConfig(NodeConfig[Operation, DaylitePersonalToken]):
    pass


ROUTES = {'list_contacts': ('GET', '/contacts'), 'get_contact': ('GET', '/contacts/{id}'), 'create_contact': ('POST', '/contacts'), 'update_contact': ('PATCH', '/contacts/{id}'), 'list_companies': ('GET', '/companies'), 'get_company': ('GET', '/companies/{id}'), 'create_company': ('POST', '/companies'), 'update_company': ('PATCH', '/companies/{id}'), 'list_tasks': ('GET', '/tasks'), 'get_task': ('GET', '/tasks/{id}'), 'create_task': ('POST', '/tasks'), 'update_task': ('PATCH', '/tasks/{id}'), 'list_notes': ('GET', '/notes'), 'get_note': ('GET', '/notes/{id}'), 'create_note': ('POST', '/notes'), 'update_note': ('PATCH', '/notes/{id}'), 'list_projects': ('GET', '/projects'), 'get_project': ('GET', '/projects/{id}'), 'create_project': ('POST', '/projects'), 'update_project': ('PATCH', '/projects/{id}'), 'list_opportunities': ('GET', '/opportunities'), 'get_opportunity': ('GET', '/opportunities/{id}'), 'create_opportunity': ('POST', '/opportunities'), 'update_opportunity': ('PATCH', '/opportunities/{id}'), 'get_token_metadata': ('GET', '/info')}

class DayliteNode(WorkflowNode):
    integration_type = "automation-daylite"
    connection_evidence = ConnectionEvidence(operation="list_contacts", noun="contacts", label_keys=("last_name", "first_name", "self"))

    @classmethod
    def get_config_model(cls):
        return DayliteConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Daylite personal token")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "record_id" in values:
            path = path.replace("{id}", str(values.pop("record_id")))
        params = values if method == "GET" else None
        body = values if method in {"POST", "PATCH"} else None
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + self.config.credentials.access_token, "Accept": "application/json"},
                params=params, json=body)
        response.raise_for_status()
        if response.status_code == 204:
            if method == "GET":
                raise ValueError("Daylite returned an unexpected empty response")
            return {"status": "success", "operation": config.operation}
        data = response.json()
        if isinstance(data, dict) and ("error" in data or "errors" in data):
            return {"status": "error", "error": data.get("error", data.get("errors"))}
        expected = list if config.operation.startswith("list_") else dict
        if not isinstance(data, expected) or (expected is list and any(not isinstance(row, dict) for row in data)):
            raise ValueError("Daylite returned an unexpected JSON response")
        return {"status": "success", "operation": config.operation, **({"items": data} if isinstance(data, list) else {"data": data})}
