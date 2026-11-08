"""Rentman account operations using a user-supplied API JWT.

Each action makes one documented request; collection reads return one page and
preserve the provider's continuation URL for explicit pagination.
"""
from __future__ import annotations
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit, parse_qsl
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.rentman.net"


class RentmanAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Rentman API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.rentman.net/",
            "x-credential-instructions": "In Rentman, open Configuration → Integrations and generate a personal API JWT. Paste the token without Bearer. Only the most recently generated token works; generating another invalidates the previous one. NoClick sends it only to api.rentman.net.",
        })
    credential_type: Literal["rentman_api_token"] = Field("rentman_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=8192, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the Rentman API token")
        value = clean_secret(value, field_name="API token", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the token, without Bearer or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(100, ge=1, le=1500, title="Page size")
    next_page_url: str | None = Field(None, max_length=8192, title="Next page URL",
        description="Paste next_page_url from the previous result to read the next page with its original parameters.")


class _ContactFields(_Input):
    name: str | None = Field(None, max_length=1000)
    firstname: str | None = Field(None, max_length=1000)
    surname: str | None = Field(None, max_length=1000)
    email_1: str | None = Field(None, max_length=254)
    phone_1: str | None = Field(None, max_length=100)
    accounting_code: str | None = Field(None, max_length=1000)
    visit_city: str | None = Field(None, max_length=1000)
    visit_street: str | None = Field(None, max_length=1000)
    visit_postalcode: str | None = Field(None, max_length=100)


class _TaskFields(_Input):
    color: str = Field(..., min_length=1, max_length=100, description="Required by Rentman for both create and update.")
    name: str | None = Field(None, max_length=1000)
    details: str | None = Field(None, max_length=100000, json_schema_extra={"ui:widget": "textarea"})
    priority: Literal["no_priority", "low_priority", "medium_priority", "high_priority"] | None = None
    deadline: datetime | None = None
    completed_at: datetime | None = None


class ListContacts(_Page):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})


class GetContact(_Input):
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., gt=0, title="Contact ID")


class ListContactpersons(_Page):
    operation: Literal["list_contactpersons"] = Field("list_contactpersons", title="List Contact Persons", json_schema_extra={"ui:hidden": True})


class GetContactPerson(_Input):
    operation: Literal["get_contact_person"] = Field("get_contact_person", title="Get Contact Person", json_schema_extra={"ui:hidden": True})
    contact_person_id: int = Field(..., gt=0, title="Contact Person ID")


class ListCrew(_Page):
    operation: Literal["list_crew"] = Field("list_crew", title="List Crew", json_schema_extra={"ui:hidden": True})


class GetCrewMember(_Input):
    operation: Literal["get_crew_member"] = Field("get_crew_member", title="Get Crew Member", json_schema_extra={"ui:hidden": True})
    crew_member_id: int = Field(..., gt=0, title="Crew Member ID")


class ListEquipment(_Page):
    operation: Literal["list_equipment"] = Field("list_equipment", title="List Equipment", json_schema_extra={"ui:hidden": True})


class GetEquipment(_Input):
    operation: Literal["get_equipment"] = Field("get_equipment", title="Get Equipment", json_schema_extra={"ui:hidden": True})
    equipment_id: int = Field(..., gt=0, title="Equipment ID")


class ListProjects(_Page):
    operation: Literal["list_projects"] = Field("list_projects", title="List Projects", json_schema_extra={"ui:hidden": True})


class GetProject(_Input):
    operation: Literal["get_project"] = Field("get_project", title="Get Project", json_schema_extra={"ui:hidden": True})
    project_id: int = Field(..., gt=0, title="Project ID")


class ListTasks(_Page):
    operation: Literal["list_tasks"] = Field("list_tasks", title="List Tasks", json_schema_extra={"ui:hidden": True})


class GetTask(_Input):
    operation: Literal["get_task"] = Field("get_task", title="Get Task", json_schema_extra={"ui:hidden": True})
    task_id: int = Field(..., gt=0, title="Task ID")


class ListInvoices(_Page):
    operation: Literal["list_invoices"] = Field("list_invoices", title="List Invoices", json_schema_extra={"ui:hidden": True})


class GetInvoice(_Input):
    operation: Literal["get_invoice"] = Field("get_invoice", title="Get Invoice", json_schema_extra={"ui:hidden": True})
    invoice_id: int = Field(..., gt=0, title="Invoice ID")


class ListQuotes(_Page):
    operation: Literal["list_quotes"] = Field("list_quotes", title="List Quotes", json_schema_extra={"ui:hidden": True})


class GetQuote(_Input):
    operation: Literal["get_quote"] = Field("get_quote", title="Get Quote", json_schema_extra={"ui:hidden": True})
    quote_id: int = Field(..., gt=0, title="Quote ID")


class CreateContact(_ContactFields):
    operation: Literal["create_contact"] = Field("create_contact", title="Create Contact", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    type: Literal["private", "company"] = "company"


class UpdateContact(_ContactFields):
    operation: Literal["update_contact"] = Field("update_contact", title="Update Contact", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., gt=0)

    @model_validator(mode="after")
    def changes(self):
        if not any(getattr(self, k) is not None for k in _ContactFields.model_fields):
            raise ValueError("Supply at least one contact field to update")
        return self


class CreateProject(_Input):
    operation: Literal["create_project"] = Field("create_project", title="Create Project", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    reference: str | None = Field(None, max_length=1000)
    number: str | None = Field(None, max_length=1000)


class CreateTask(_TaskFields):
    operation: Literal["create_task"] = Field("create_task", title="Create Task", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)


class UpdateTask(_TaskFields):
    operation: Literal["update_task"] = Field("update_task", title="Update Task", json_schema_extra={"ui:hidden": True})
    task_id: int = Field(..., gt=0)


class DeleteTask(_Input):
    operation: Literal["delete_task"] = Field("delete_task", title="Delete Task", description="Permanently delete the selected task.", json_schema_extra={"ui:hidden": True})
    task_id: int = Field(..., gt=0)


class ListProjectEquipment(_Page):
    operation: Literal["list_project_equipment"] = Field("list_project_equipment", title="List Project Equipment", json_schema_extra={"ui:hidden": True})
    project_id: int = Field(..., gt=0)


RentmanConfig = Annotated[Union[
    ListContacts,
    GetContact,
    ListContactpersons,
    GetContactPerson,
    ListCrew,
    GetCrewMember,
    ListEquipment,
    GetEquipment,
    ListProjects,
    GetProject,
    ListTasks,
    GetTask,
    ListInvoices,
    GetInvoice,
    ListQuotes,
    GetQuote,
    CreateContact,
    UpdateContact,
    CreateProject,
    CreateTask,
    UpdateTask,
    DeleteTask,
    ListProjectEquipment
], Field(discriminator="operation")]


class RentmanFullConfig(NodeConfig[RentmanConfig, RentmanAPITokenCredential]):
    pass


ROUTES = {
    'list_contacts': ('GET', '/contacts'),
    'get_contact': ('GET', '/contacts/{id}'),
    'list_contactpersons': ('GET', '/contactpersons'),
    'get_contact_person': ('GET', '/contactpersons/{id}'),
    'list_crew': ('GET', '/crew'),
    'get_crew_member': ('GET', '/crew/{id}'),
    'list_equipment': ('GET', '/equipment'),
    'get_equipment': ('GET', '/equipment/{id}'),
    'list_projects': ('GET', '/projects'),
    'get_project': ('GET', '/projects/{id}'),
    'list_tasks': ('GET', '/tasks'),
    'get_task': ('GET', '/tasks/{id}'),
    'list_invoices': ('GET', '/invoices'),
    'get_invoice': ('GET', '/invoices/{id}'),
    'list_quotes': ('GET', '/quotes'),
    'get_quote': ('GET', '/quotes/{id}'),
    'create_contact': ('POST', '/contacts'),
    'update_contact': ('PUT', '/contacts/{id}'),
    'create_project': ('POST', '/projects'),
    'create_task': ('POST', '/tasks'),
    'update_task': ('PUT', '/tasks/{id}'),
    'delete_task': ('DELETE', '/tasks/{id}'),
    'list_project_equipment': ('GET', '/projects/{id}/projectequipment'),
}


def _page_url(value, path):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.netloc != "api.rentman.net"
                or parsed.path != path or parsed.fragment or not parsed.query
                or any(c.isspace() or ord(c) < 33 for c in value)):
            raise ValueError()
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        if len({k for k, _ in pairs}) != len(pairs) or not any(k in {"cursor", "cursor_after"} and v for k, v in pairs):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("Use the Rentman next_page_url for this collection") from None
    return value


class RentmanNode(WorkflowNode):
    integration_type = "automation-rentman"
    connection_evidence = ConnectionEvidence(noun="projects", operation="list_projects")

    @classmethod
    def get_config_model(cls):
        return RentmanFullConfig

    @classmethod
    def parse_config(cls, config_data):
        cls._check_credential_family(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._check_credential_family(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    @staticmethod
    def _check_credential_family(config_data):
        credential = config_data.get("credentials")
        if isinstance(credential, dict) and "credential_type" in credential and credential["credential_type"] != "rentman_api_token":
            raise ValueError("Attach a Rentman API token credential")

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Attach a Rentman API token")
        config = self.config.config
        method, template = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        identifier = next((v for k, v in values.items() if k.endswith("_id")), None)
        path = template.replace("{id}", str(identifier))
        url = BASE + path
        params = None
        body = None
        listing = config.operation.startswith("list_")
        if listing:
            if config.next_page_url:
                url = _page_url(config.next_page_url, path)
            else:
                params = {"limit": config.limit}
        elif method in {"POST", "PUT"}:
            body = {k: v for k, v in values.items() if k != "operation" and not k.endswith("_id")}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, url, params=params, json=body,
                headers={"Authorization": "Bearer " + credential.api_token,
                         "Accept": "application/json", "Content-Type": "application/json"})
        if not response.is_success:
            # Keep the provider's rejection verbatim for the shared connect verdict.
            raise ValueError(f"Rentman HTTP {response.status_code}: {response.text[:2000]}")
        if method == "DELETE":
            return {"status": "success", "deleted_id": identifier, "http_status": response.status_code}
        if len(response.content) > 5_500_000:
            raise ValueError("Rentman response exceeds its documented size limit")
        payload = response.json()
        if not isinstance(payload, dict) or "data" not in payload:
            raise ValueError("Rentman response is missing data")
        data = payload["data"]
        if listing:
            if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
                raise ValueError("Rentman collection data must be an array of objects")
            next_url = payload.get("next_page_url")
            if next_url is not None:
                _page_url(next_url, path)
                if next_url == url:
                    raise ValueError("Rentman returned a repeated continuation")
        elif not isinstance(data, dict):
            raise ValueError("Rentman item data must be an object")
        return {**payload, "status": "success", "operation": config.operation, "http_status": response.status_code}
