"""Samdock CRM operations from the published Microservices OpenAPI 1.0.0.

Bearer tokens are supplied by the person connecting. Paths are case sensitive.
Updates send the contract's complete required DTO fields. Each operation makes
one request; writes are never retried automatically. No webhook registration or
created/updated ordering/filtering is published in this contract.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://samdock.app"


class SamdockTokenCredential(BaseModel):
    model_config = ConfigDict(title="Samdock API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://samdock.readme.io/reference/personscontroller_browse",
            "x-credential-instructions": "Paste your existing Samdock bearer access token. NoClick sends it to the production Samdock API and reads your organizations to check the connection. The published API does not provide token creation or refresh endpoints; replace an expired token here.",
        })
    credential_type: Literal["samdock_api_token"] = Field("samdock_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the bearer token without the Bearer prefix or whitespace")
        return value


class _Fields(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)


class _Resource(_Fields):
    id: str = Field(..., title="Record ID", min_length=1, description="The existing Samdock record ID.")

    @field_validator("id")
    @classmethod
    def identifier(cls, value):
        if value in {".", ".."} or any(c in value for c in "/?#\\") or any(ord(c) < 32 for c in value):
            raise ValueError("Use one Samdock record ID, without a URL or path")
        return value


class _Person(_Fields):
    tenant_id: str = Field(..., title="Tenant ID", min_length=1, description="Required _tenantID in the published PersonDTO.")
    record_id: str = Field(..., title="Person Body ID", min_length=1, description="Required _id in the published PersonDTO.")
    last_name: str = Field(..., title="Last Name", min_length=1)
    gender: str = Field(..., title="Gender")
    name_prefix: str = Field(..., title="Name Prefix")
    name_suffix: str = Field(..., title="Name Suffix")
    first_name: str | None = Field(None, title="First Name")
    email: str | None = Field(None, title="Email")
    phone_number: str | None = Field(None, title="Phone Number")
    mobile_number: str | None = Field(None, title="Mobile Number")
    website: str | None = Field(None, title="Website")


class _Organization(_Fields):
    tenant_id: str = Field(..., title="Tenant ID", min_length=1, description="Required _tenantID in the published OrganizationDTO.")
    record_id: str = Field(..., title="Organization Body ID", min_length=1, description="Required _id in the published OrganizationDTO.")
    name: str = Field(..., title="Name", min_length=1)
    email: str | None = Field(None, title="Email")
    phone_number: str | None = Field(None, title="Phone Number")
    website: str | None = Field(None, title="Website")
    is_customer: bool | None = Field(None, title="Is Customer")
    contact_person: str | None = Field(None, title="Contact Person ID")


class _Deal(_Fields):
    name: str = Field(..., title="Name", min_length=1)
    record_id: str | None = Field(None, title="Deal Body ID")
    contact_person: str | None = Field(None, title="Contact Person ID")
    positions_estimated: float | None = Field(None, title="Estimated Value")
    is_archived: bool | None = Field(None, title="Archived")


class _Task(_Fields):
    tenant_id: str = Field(..., title="Tenant ID", min_length=1, description="Required _tenantID in the published TaskDTO.")
    record_id: str = Field(..., title="Task Body ID", min_length=1, description="Required _id in the published TaskDTO.")
    name: str | None = Field(None, title="Name")
    description: str | None = Field(None, title="Description", json_schema_extra={"ui:widget": "textarea"})
    person_id: str | None = Field(None, title="Person ID")
    organization_id: str | None = Field(None, title="Organization ID")
    deal_id: str | None = Field(None, title="Deal ID")
    user_id: str | None = Field(None, title="Assignee User ID")
    priority: str | None = Field(None, title="Priority")
    due_date: float | None = Field(None, title="Due Date", description="Samdock numeric dueDate value.")
    start_date: float | None = Field(None, title="Start Date", description="Samdock numeric startDate value.")
    completion_date: float | None = Field(None, title="Completion Date", description="Samdock numeric completionDate value.")


class _Page(_Fields):
    limit: int = Field(100, title="Limit", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0, description="Pass the next offset to retrieve another page.")


class ListPersons(_Fields):
    operation: Literal["list_persons"] = Field("list_persons", title="List Persons", json_schema_extra={"ui:hidden": True})


class GetPerson(_Resource):
    operation: Literal["get_person"] = Field("get_person", title="Get Person", json_schema_extra={"ui:hidden": True})


class CreatePerson(_Person):
    operation: Literal["create_person"] = Field("create_person", title="Create Person", json_schema_extra={"ui:hidden": True})


class UpdatePerson(_Resource, _Person):
    operation: Literal["update_person"] = Field("update_person", title="Update Person", json_schema_extra={"ui:hidden": True})


class DeletePerson(_Resource):
    operation: Literal["delete_person"] = Field("delete_person", title="Delete Person", json_schema_extra={"ui:hidden": True})


class ListOrganizations(_Fields):
    operation: Literal["list_organizations"] = Field("list_organizations", title="List Organizations", json_schema_extra={"ui:hidden": True})


class GetOrganization(_Resource):
    operation: Literal["get_organization"] = Field("get_organization", title="Get Organization", json_schema_extra={"ui:hidden": True})


class CreateOrganization(_Organization):
    operation: Literal["create_organization"] = Field("create_organization", title="Create Organization", json_schema_extra={"ui:hidden": True})


class UpdateOrganization(_Resource, _Organization):
    operation: Literal["update_organization"] = Field("update_organization", title="Update Organization", json_schema_extra={"ui:hidden": True})


class DeleteOrganization(_Resource):
    operation: Literal["delete_organization"] = Field("delete_organization", title="Delete Organization", json_schema_extra={"ui:hidden": True})


class ListLeads(_Fields):
    operation: Literal["list_leads"] = Field("list_leads", title="List Leads", json_schema_extra={"ui:hidden": True})


class CreateLead(_Deal):
    operation: Literal["create_lead"] = Field("create_lead", title="Create Lead", json_schema_extra={"ui:hidden": True})


class UpdateLead(_Resource, _Deal):
    operation: Literal["update_lead"] = Field("update_lead", title="Update Lead", json_schema_extra={"ui:hidden": True})


class ChangeDealStage(_Resource):
    operation: Literal["change_deal_stage"] = Field("change_deal_stage", title="Change Deal Stage", json_schema_extra={"ui:hidden": True})
    pipeline_id: str = Field(..., title="Pipeline ID", min_length=1)
    stage_id: str = Field(..., title="Stage ID", min_length=1)


class ListDeals(_Fields):
    operation: Literal["list_deals"] = Field("list_deals", title="List Deals", json_schema_extra={"ui:hidden": True})


class GetDeal(_Resource):
    operation: Literal["get_deal"] = Field("get_deal", title="Get Deal", json_schema_extra={"ui:hidden": True})


class CreateDeal(_Deal):
    operation: Literal["create_deal"] = Field("create_deal", title="Create Deal", json_schema_extra={"ui:hidden": True})


class UpdateDeal(_Resource, _Deal):
    operation: Literal["update_deal"] = Field("update_deal", title="Update Deal", json_schema_extra={"ui:hidden": True})


class DeleteDeal(_Resource):
    operation: Literal["delete_deal"] = Field("delete_deal", title="Delete Deal", json_schema_extra={"ui:hidden": True})


class ListTasks(_Page):
    operation: Literal["list_tasks"] = Field("list_tasks", title="List Tasks", json_schema_extra={"ui:hidden": True})


class GetTask(_Resource):
    operation: Literal["get_task"] = Field("get_task", title="Get Task", json_schema_extra={"ui:hidden": True})


class CreateTask(_Task):
    operation: Literal["create_task"] = Field("create_task", title="Create Task", json_schema_extra={"ui:hidden": True})


class UpdateTask(_Resource, _Task):
    operation: Literal["update_task"] = Field("update_task", title="Update Task", json_schema_extra={"ui:hidden": True})


class DeleteTask(_Resource):
    operation: Literal["delete_task"] = Field("delete_task", title="Delete Task", json_schema_extra={"ui:hidden": True})


class ListPipelines(_Fields):
    operation: Literal["list_pipelines"] = Field("list_pipelines", title="List Pipelines", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[ListPersons, GetPerson, CreatePerson, UpdatePerson, DeletePerson, ListOrganizations, GetOrganization, CreateOrganization, UpdateOrganization, DeleteOrganization, ListLeads, CreateLead, UpdateLead, ChangeDealStage, ListDeals, GetDeal, CreateDeal, UpdateDeal, DeleteDeal, ListTasks, GetTask, CreateTask, UpdateTask, DeleteTask, ListPipelines], Field(discriminator="operation")]


class SamdockNodeConfig(NodeConfig[Operation, SamdockTokenCredential]):
    pass


ROUTES = {'list_persons': ('GET', '/api/contacts/Persons'), 'get_person': ('GET', '/api/contacts/persons/{id}'), 'create_person': ('POST', '/api/contacts/Persons'), 'update_person': ('PATCH', '/api/contacts/persons/{id}'), 'delete_person': ('DELETE', '/api/contacts/persons/{id}'), 'list_organizations': ('GET', '/api/contacts/Organizations'), 'get_organization': ('GET', '/api/contacts/organizations/{id}'), 'create_organization': ('POST', '/api/contacts/Organizations'), 'update_organization': ('PATCH', '/api/contacts/organizations/{id}'), 'delete_organization': ('DELETE', '/api/contacts/organizations/{id}'), 'list_leads': ('GET', '/api/deals/leads'), 'create_lead': ('POST', '/api/deals/leads'), 'update_lead': ('PATCH', '/api/deals/leads/{id}'), 'change_deal_stage': ('PATCH', '/api/deals/{id}/stage'), 'list_deals': ('GET', '/api/deals'), 'get_deal': ('GET', '/api/deals/{id}'), 'create_deal': ('POST', '/api/deals'), 'update_deal': ('PATCH', '/api/deals/{id}'), 'delete_deal': ('DELETE', '/api/deals/{id}'), 'list_tasks': ('GET', '/api/activities/tasks'), 'get_task': ('GET', '/api/activities/tasks/{id}'), 'create_task': ('POST', '/api/activities/tasks'), 'update_task': ('PATCH', '/api/activities/tasks/{id}'), 'delete_task': ('DELETE', '/api/activities/tasks/{id}'), 'list_pipelines': ('GET', '/api/deals/pipelines')}

# Only fields exposed by the operation are sent, using the contract's wire names.
BODY_FIELDS = {
    "pipeline_id": "pipelineID", "stage_id": "stageID",
    "tenant_id": "_tenantID", "record_id": "_id", "last_name": "lastName",
    "first_name": "firstName", "name_prefix": "namePrefix", "name_suffix": "nameSuffix",
    "phone_number": "phoneNumber", "mobile_number": "mobileNumber",
    "is_customer": "isCustomer", "contact_person": "contactPerson",
    "positions_estimated": "positionsEstimated", "is_archived": "isArchived",
    "person_id": "_personID", "organization_id": "_organizationID",
    "deal_id": "_dealID", "user_id": "_userID", "due_date": "dueDate",
    "start_date": "startDate", "completion_date": "completionDate",
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class SamdockNode(WorkflowNode):
    integration_type = "automation-samdock"
    connection_evidence = ConnectionEvidence(noun="organizations", operation="list_organizations", label_keys=("name", "_id"))

    @classmethod
    def get_config_model(cls):
        return SamdockNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect your Samdock API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, path = ROUTES[op.operation]
        if "{id}" in path:
            path = path.replace("{id}", quote(op.id, safe=""))
        kwargs = {}
        if isinstance(op, _Page):
            kwargs["params"] = {"limit": op.limit, "offset": op.offset}
        if method in {"POST", "PATCH"}:
            values = op.model_dump(exclude_none=True, exclude={"operation", "id"})
            kwargs["json"] = {BODY_FIELDS.get(k, k): v for k, v in values.items()}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        except (httpx.HTTPError, OSError):
            raise ValueError("Samdock request did not complete; inspect the record before retrying a write") from None
        status = response.status_code
        if not 200 <= status < 300:
            try:
                error = response.json()
                message = error.get("message", error.get("error", "Samdock request failed")) if isinstance(error, dict) else "Samdock request failed"
            except ValueError:
                message = "Samdock request failed"
            result = {"status": "error", "error": message, "http_status": status}
        else:
            # Several documented writes acknowledge acceptance with no response schema/body.
            try:
                data = response.json() if response.content.strip() else None
            except ValueError:
                raise ValueError("Samdock returned an invalid JSON response") from None
            if method == "GET" and data is None:
                raise ValueError("Samdock returned an empty read response")
            if isinstance(data, dict) and (data.get("error") or data.get("errors") or data.get("success") is False):
                result = {"status": "error", "error": data, "http_status": status}
            else:
                result = {"status": "success", "data": data, "http_status": status,
                          "operation": op.operation}
        result = _redact(result, token)
        await self.emit(result)
        return result
