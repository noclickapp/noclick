"""webCRM REST v1: fixed CRM operations using a manually supplied bearer token.

Contract: https://api.webcrm.com/swagger/v1/swagger.json (v1).
Access tokens expire; the person replaces them, with no hidden login or refresh.
Each operation makes exactly one request. PUT uses the provider's update route.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
import re
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

API_ROOT = "https://api.webcrm.com"


class WebCRMAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="webCRM Access Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://api.webcrm.com/documentation/index.html",
        "x-credential-instructions": "Paste an AccessToken returned by webCRM's POST /Auth/ApiLogin (authCode is your application token from Configuration → Integration → API → REST). Enable organisation read access for connection verification, plus read/write access for the records you use. Paste the access token, not the application token. Access tokens expire: replace this credential's token when webCRM rejects it. NoClick does not sign in or refresh it automatically.",
    })
    credential_type: Literal["webcrm_access_token"] = Field("webcrm_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", min_length=1, max_length=8192, repr=False,
        description="The AccessToken from webCRM's token response, without the Bearer prefix. Replace it when it expires.",
        json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token")
    @classmethod
    def bearer_value(cls, value):
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", value):
            raise ValueError("Paste the access token without the Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    page: int = Field(1, ge=1, le=1000000, title="Page", description="One page per execution; increment to continue.")
    page_size: int = Field(50, ge=1, le=1000, title="Page Size")
    sort_order: Literal["Ascending", "Descending"] = Field("Ascending", title="Sort Order")


class ListOrganisations(_Page):
    operation: Literal["list_organisations"] = Field("list_organisations", title="List Organisations", json_schema_extra={"ui:hidden": True})


class GetOrganisation(_Input):
    operation: Literal["get_organisation"] = Field("get_organisation", title="Get Organisation", json_schema_extra={"ui:hidden": True})
    organisation_id: int = Field(..., ge=1, le=2147483647, title="Organisation ID")


class CreateOrganisation(_Input):
    operation: Literal["create_organisation"] = Field("create_organisation", title="Create Organisation", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., title="Name", max_length=200, min_length=1)
    city: str | None = Field(None, title="City", max_length=50)
    telephone: str | None = Field(None, title="Telephone", max_length=50)


class UpdateOrganisation(_Input):
    operation: Literal["update_organisation"] = Field("update_organisation", title="Update Organisation", json_schema_extra={"ui:hidden": True})
    organisation_id: int = Field(..., ge=1, le=2147483647, title="Organisation ID")
    name: str = Field(..., title="Name", max_length=200, min_length=1)
    city: str | None = Field(None, title="City", max_length=50)
    telephone: str | None = Field(None, title="Telephone", max_length=50)


class ListPersons(_Page):
    operation: Literal["list_persons"] = Field("list_persons", title="List Persons", json_schema_extra={"ui:hidden": True})


class GetPerson(_Input):
    operation: Literal["get_person"] = Field("get_person", title="Get Person", json_schema_extra={"ui:hidden": True})
    person_id: int = Field(..., ge=1, le=2147483647, title="Person ID")


class CreatePerson(_Input):
    operation: Literal["create_person"] = Field("create_person", title="Create Person", json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., title="First Name", max_length=50, min_length=1)
    last_name: str = Field(..., title="Last Name", max_length=50, min_length=1)
    email: str | None = Field(None, title="Email", max_length=100)
    organisation_id: int = Field(..., title="Organisation Id", ge=1, le=2147483647)


class UpdatePerson(_Input):
    operation: Literal["update_person"] = Field("update_person", title="Update Person", json_schema_extra={"ui:hidden": True})
    person_id: int = Field(..., ge=1, le=2147483647, title="Person ID")
    first_name: str = Field(..., title="First Name", max_length=50, min_length=1)
    last_name: str = Field(..., title="Last Name", max_length=50, min_length=1)
    email: str | None = Field(None, title="Email", max_length=100)
    organisation_id: int = Field(..., title="Organisation Id", ge=1, le=2147483647)


class ListOpportunities(_Page):
    operation: Literal["list_opportunities"] = Field("list_opportunities", title="List Opportunities", json_schema_extra={"ui:hidden": True})


class GetOpportunity(_Input):
    operation: Literal["get_opportunity"] = Field("get_opportunity", title="Get Opportunity", json_schema_extra={"ui:hidden": True})
    opportunity_id: int = Field(..., ge=1, le=2147483647, title="Opportunity ID")


class CreateOpportunity(_Input):
    operation: Literal["create_opportunity"] = Field("create_opportunity", title="Create Opportunity", json_schema_extra={"ui:hidden": True})
    description: str = Field(..., title="Description", max_length=50, min_length=1)
    organisation_id: int = Field(..., title="Organisation Id", ge=1, le=2147483647)
    person_id: int | None = Field(None, title="Person Id", ge=1, le=2147483647)


class UpdateOpportunity(_Input):
    operation: Literal["update_opportunity"] = Field("update_opportunity", title="Update Opportunity", json_schema_extra={"ui:hidden": True})
    opportunity_id: int = Field(..., ge=1, le=2147483647, title="Opportunity ID")
    description: str = Field(..., title="Description", max_length=50, min_length=1)
    organisation_id: int = Field(..., title="Organisation Id", ge=1, le=2147483647)
    person_id: int | None = Field(None, title="Person Id", ge=1, le=2147483647)


class ListActivities(_Page):
    operation: Literal["list_activities"] = Field("list_activities", title="List Activities", json_schema_extra={"ui:hidden": True})


class GetActivity(_Input):
    operation: Literal["get_activity"] = Field("get_activity", title="Get Activity", json_schema_extra={"ui:hidden": True})
    activity_id: int = Field(..., ge=1, le=2147483647, title="Activity ID")


class CreateActivity(_Input):
    operation: Literal["create_activity"] = Field("create_activity", title="Create Activity", json_schema_extra={"ui:hidden": True})
    description: str = Field(..., title="Description", max_length=100, min_length=1)
    organisation_id: int = Field(..., title="Organisation Id", ge=1, le=2147483647)
    person_id: int | None = Field(None, title="Person Id", ge=1, le=2147483647)
    status: Literal["Planned", "Active", "Completed"] | None = Field(None, title="Status")


class UpdateActivity(_Input):
    operation: Literal["update_activity"] = Field("update_activity", title="Update Activity", json_schema_extra={"ui:hidden": True})
    activity_id: int = Field(..., ge=1, le=2147483647, title="Activity ID")
    description: str = Field(..., title="Description", max_length=100, min_length=1)
    organisation_id: int = Field(..., title="Organisation Id", ge=1, le=2147483647)
    person_id: int | None = Field(None, title="Person Id", ge=1, le=2147483647)
    status: Literal["Planned", "Active", "Completed"] | None = Field(None, title="Status")


class ListSupportCases(_Page):
    operation: Literal["list_support_cases"] = Field("list_support_cases", title="List Support Cases", json_schema_extra={"ui:hidden": True})


class GetSupportCase(_Input):
    operation: Literal["get_support_case"] = Field("get_support_case", title="Get Support Case", json_schema_extra={"ui:hidden": True})
    support_case_id: int = Field(..., ge=1, le=2147483647, title="Support Case ID")


class CreateSupportCase(_Input):
    operation: Literal["create_support_case"] = Field("create_support_case", title="Create Support Case", json_schema_extra={"ui:hidden": True})
    subject: str = Field(..., title="Subject", max_length=150, min_length=1)
    description: str | None = Field(None, title="Description")
    organisation_id: int = Field(..., title="Organisation Id", ge=1, le=2147483647)
    person_id: int | None = Field(None, title="Person Id", ge=1, le=2147483647)
    status: Literal["Created", "Ongoing", "Closed"] | None = Field(None, title="Status")


class UpdateSupportCase(_Input):
    operation: Literal["update_support_case"] = Field("update_support_case", title="Update Support Case", json_schema_extra={"ui:hidden": True})
    support_case_id: int = Field(..., ge=1, le=2147483647, title="Support Case ID")
    subject: str = Field(..., title="Subject", max_length=150, min_length=1)
    description: str | None = Field(None, title="Description")
    organisation_id: int = Field(..., title="Organisation Id", ge=1, le=2147483647)
    person_id: int | None = Field(None, title="Person Id", ge=1, le=2147483647)
    status: Literal["Created", "Ongoing", "Closed"] | None = Field(None, title="Status")


class SearchPersons(_Page):
    operation: Literal["search_persons"] = Field("search_persons", title="Search Persons", json_schema_extra={"ui:hidden": True})
    search: str = Field(..., min_length=1, title="Name, Email or Telephone")


class ListOrganisationPersons(_Page):
    operation: Literal["list_organisation_persons"] = Field("list_organisation_persons", title="List Organisation Persons", json_schema_extra={"ui:hidden": True})
    organisation_id: int = Field(..., ge=1, le=2147483647, title="Organisation ID")


class ListUsers(_Page):
    operation: Literal["list_users"] = Field("list_users", title="List Users", json_schema_extra={"ui:hidden": True})


WebCRMConfig = Annotated[Union[ListOrganisations, GetOrganisation, CreateOrganisation, UpdateOrganisation, ListPersons, GetPerson, CreatePerson, UpdatePerson, ListOpportunities, GetOpportunity, CreateOpportunity, UpdateOpportunity, ListActivities, GetActivity, CreateActivity, UpdateActivity, ListSupportCases, GetSupportCase, CreateSupportCase, UpdateSupportCase, SearchPersons, ListOrganisationPersons, ListUsers], Field(discriminator="operation")]


class WebCRMFullConfig(NodeConfig[WebCRMConfig, WebCRMAccessTokenCredential]):
    pass


ROUTES = {'list_organisations': ('GET', '/Organisations', None, 'Organisation'),
 'get_organisation': ('GET', '/Organisations/{id}', 'organisation', 'Organisation'),
 'create_organisation': ('POST', '/Organisations', None, 'Organisation'),
 'update_organisation': ('PUT', '/Organisations/{id}', 'organisation', 'Organisation'),
 'list_persons': ('GET', '/Persons', None, 'Person'),
 'get_person': ('GET', '/Persons/{id}', 'person', 'Person'),
 'create_person': ('POST', '/Persons', None, 'Person'),
 'update_person': ('PUT', '/Persons/{id}', 'person', 'Person'),
 'list_opportunities': ('GET', '/Opportunities', None, 'Opportunity'),
 'get_opportunity': ('GET', '/Opportunities/{id}', 'opportunity', 'Opportunity'),
 'create_opportunity': ('POST', '/Opportunities', None, 'Opportunity'),
 'update_opportunity': ('PUT', '/Opportunities/{id}', 'opportunity', 'Opportunity'),
 'list_activities': ('GET', '/Activities', None, 'Activity'),
 'get_activity': ('GET', '/Activities/{id}', 'activity', 'Activity'),
 'create_activity': ('POST', '/Activities', None, 'Activity'),
 'update_activity': ('PUT', '/Activities/{id}', 'activity', 'Activity'),
 'list_support_cases': ('GET', '/SupportCases', None, 'SupportCase'),
 'get_support_case': ('GET', '/SupportCases/{id}', 'support_case', 'SupportCase'),
 'create_support_case': ('POST', '/SupportCases', None, 'SupportCase'),
 'update_support_case': ('PUT', '/SupportCases/{id}', 'support_case', 'SupportCase'),
 'search_persons': ('GET', '/Persons/Search', None, 'Person'),
 'list_organisation_persons': ('GET', '/Organisations/{id}/Persons', 'organisation', 'Person'),
 'list_users': ('GET', '/Users', None, 'User')}
FIELDS = {'Organisation': {'name': 'OrganisationName',
                  'city': 'OrganisationCity',
                  'telephone': 'OrganisationTelephone'},
 'Person': {'first_name': 'PersonFirstName',
            'last_name': 'PersonLastName',
            'email': 'PersonEmail',
            'organisation_id': 'PersonOrganisationId'},
 'Opportunity': {'description': 'OpportunityDescription',
                 'organisation_id': 'OpportunityOrganisationId',
                 'person_id': 'OpportunityPersonId'},
 'Activity': {'description': 'ActivityDescription',
              'organisation_id': 'ActivityOrganisationId',
              'person_id': 'ActivityPersonId',
              'status': 'ActivityStatus'},
 'SupportCase': {'subject': 'SupportCaseSubject',
                 'description': 'SupportCaseDescription',
                 'organisation_id': 'SupportCaseOrganisationId',
                 'person_id': 'SupportCasePersonId',
                 'status': 'SupportCaseStatus'}}


class WebCRMNode(WorkflowNode):
    integration_type = "automation-webcrm"
    connection_evidence = ConnectionEvidence(
        noun="organisations", operation="list_organisations",
        label_keys=("OrganisationName", "OrganisationId"),
    )

    @classmethod
    def get_config_model(cls):
        return WebCRMFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a webCRM access token")
        config = self.config.config
        operation = config.operation
        method, route, id_field, prefix = ROUTES[operation]
        identifier = getattr(config, id_field + "_id") if id_field else None
        route = route.replace("{id}", str(identifier))
        params = {}
        body = None
        if isinstance(config, _Page):
            params = {"Page": config.page, "Size": config.page_size, "SortOrder": config.sort_order}
        if operation == "search_persons":
            params["input"] = config.search
        if method in {"POST", "PUT"}:
            # DTO identifiers are required even on creation (zero requests a new ID).
            body = {prefix + "Id": identifier if method == "PUT" else 0}
            body.update({wire: getattr(config, field) for field, wire in FIELDS[prefix].items()
                         if getattr(config, field) is not None})
        token = self.config.credentials.access_token
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, API_ROOT + route, params=params,
                                            headers=headers, **({"json": body} if body is not None else {}))
        if response.status_code != 200:
            # Preserve the provider's rejection text for manual connection evidence.
            message = response.text[:1000].replace(token, "[redacted]") or response.reason_phrase
            return {"status": "error", "http_status": response.status_code,
                    "error": f"webCRM HTTP {response.status_code}: {message}"}
        if method == "PUT":
            # The published update responses have no response-body schema.
            return {"status": "success", "id": identifier}
        data = response.json() if response.content else None
        if isinstance(config, _Page):
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError("webCRM returned an invalid record list")
            # A full page may have a successor; the API provides no total or cursor.
            return {"status": "success", "items": data, "page": config.page,
                    "next_page": config.page + 1 if len(data) == config.page_size else None}
        if method == "POST":
            if type(data) is not int or data < 1:
                raise ValueError("webCRM did not return a new record ID")
            return {"status": "success", "id": data}
        if method == "GET" and not isinstance(data, dict):
            raise ValueError("webCRM returned an invalid record")
        return {"status": "success", "data": data}
