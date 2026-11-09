"""Autotask REST v1: bounded reads and explicit creates/patches.

Contract: https://webservices5.autotask.net/ATServicesRest/swagger/docs/v1
Authentication: https://ww3.autotask.net/help/DeveloperHelp/Content/APIs/REST/General_Topics/REST_Security_Auth.htm
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

AUTH_DOC = "https://ww3.autotask.net/help/DeveloperHelp/Content/APIs/REST/General_Topics/REST_Security_Auth.htm"
ZONE_DOC = "https://ww3.autotask.net/help/DeveloperHelp/Content/APIs/REST/API_Calls/REST_ZoneInformation.htm"
ZONE_HOSTS = {f"webservices{n}.autotask.net" for n in (1, 2, 3, 4, 5, 6, 11, 12, 14, 15, 16, 17, 18, 19, 22, 24, 25, 26, 28, 29, 30, 31)} | {"prde.autotask.net", "pres.autotask.net"}


class AutotaskAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Autotask API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": AUTH_DOC,
            "x-credential-instructions": "Use an API User (API-only) resource. Paste its username, secret and API tracking identifier from the resource Security tab. Select the API URL for your zone; see Autotask's zone URL documentation. Permissions follow this API user's security level."})
    credential_type: Literal["autotask_api_key"] = Field("autotask_api_key", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, max_length=254, title="API username")
    secret: str = Field(..., min_length=1, max_length=4096, title="API secret", repr=False, json_schema_extra={"ui:widget": "password"})
    api_integration_code: str = Field(..., min_length=1, max_length=4096, title="API integration code", repr=False, json_schema_extra={"ui:widget": "password"})
    api_base_url: str = Field("https://webservices5.autotask.net/ATServicesRest", title="Regional API URL", description="Paste your zone's HTTPS API root ending in /atservicesrest.", json_schema_extra={"ui:help": ZONE_DOC})

    @field_validator("api_base_url", mode="before")
    @classmethod
    def regional_url(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the regional HTTPS API root")
        p = urlsplit(value.strip())
        if (p.scheme != "https" or p.netloc.lower() not in ZONE_HOSTS or p.username or p.password
                or p.query or p.fragment or p.path.rstrip("/").lower() != "/atservicesrest"):
            raise ValueError("Use a published Autotask regional HTTPS API URL ending in /atservicesrest")
        return "https://" + p.netloc.lower() + "/ATServicesRest"

    @field_validator("username", "secret", "api_integration_code", mode="before")
    @classmethod
    def header_value(cls, value, info):
        if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("Paste a nonempty API credential without control characters")
        return value.strip() if info.field_name == "username" else clean_secret(value, field_name=info.field_name)


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Record(_Input):
    id: int = Field(..., ge=1, title="Record ID")


class _Query(_Input):
    max_records: int = Field(100, ge=1, le=500, title="Maximum records")
    filter_json: str = Field('[{"op":"exist","field":"id"}]', max_length=32000, title="Filter (JSON array)",
        description='Autotask filter expressions. For another page, add an id greater than the returned next_after_id; retain your other filters. Example: [{"op":"gt","field":"id","value":123}].',
        json_schema_extra={"ui:widget": "textarea"})

    @field_validator("filter_json")
    @classmethod
    def filters(cls, value):
        try:
            parsed = json.loads(value)
        except (ValueError, RecursionError):
            raise ValueError("Filter must be a JSON array of Autotask expressions") from None
        _validate_filters(parsed)
        return value


def _validate_filters(items, depth=0):
    if not isinstance(items, list) or not 1 <= len(items) <= 50 or depth > 5:
        raise ValueError("Use one to fifty filters, nested at most five levels")
    for item in items:
        if not isinstance(item, dict) or set(item) - {"op", "field", "value", "udf", "items"}:
            raise ValueError("Invalid Autotask filter properties")
        op = item.get("op")
        if op in {"and", "or"}:
            if set(item) != {"op", "items"}:
                raise ValueError("Logical filters take op and items")
            _validate_filters(item["items"], depth + 1)
            continue
        if op not in {"eq", "noteq", "gt", "gte", "lt", "lte", "beginsWith", "endsWith", "contains", "in", "notIn", "exist", "notExist"}:
            raise ValueError("Unsupported Autotask filter operator")
        name = item.get("field")
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            raise ValueError("A filter needs a field name")
        if "udf" in item and type(item["udf"]) is not bool:
            raise ValueError("udf must be a boolean")
        if op not in {"exist", "notExist"} and "value" not in item:
            raise ValueError("A comparison filter needs a value")
        if "items" in item:
            raise ValueError("Only logical operators take nested items")
        if "value" in item:
            v = item["value"]
            if not (v is None or type(v) in {str, int, bool} or (isinstance(v, list) and len(v) <= 100 and all(type(x) in {str, int} for x in v))):
                raise ValueError("Filter values must be scalar or a bounded string/integer array")


class _Patch(_Record):
    @model_validator(mode="after")
    def nonempty_patch(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in ({"operation", "id", "company_id"} if self.operation == "update_contact" else {"operation", "id"})):
            raise ValueError("Choose at least one field to update")
        return self


class _Dates(_Input):
    @field_validator("due_date_time", "date_worked", mode="before", check_fields=False)
    @classmethod
    def dates(cls, value, info):
        if value is not None and info.field_name in {"due_date_time", "date_worked"}:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if "T" not in value:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise ValueError("Use an ISO 8601 date and time in UTC") from None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return value


class ListTickets(_Query):
    operation: Literal["list_tickets"] = Field("list_tickets", title="List Tickets", json_schema_extra={"ui:hidden": True})


class GetTicket(_Record):
    operation: Literal["get_ticket"] = Field("get_ticket", title="Get Ticket", json_schema_extra={"ui:hidden": True})


class ListCompanies(_Query):
    operation: Literal["list_companies"] = Field("list_companies", title="List Companies", json_schema_extra={"ui:hidden": True})


class GetCompany(_Record):
    operation: Literal["get_company"] = Field("get_company", title="Get Company", json_schema_extra={"ui:hidden": True})


class ListContacts(_Query):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})


class GetContact(_Record):
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})


class ListTimeEntries(_Query):
    operation: Literal["list_time_entries"] = Field("list_time_entries", title="List Time Entries", json_schema_extra={"ui:hidden": True})


class GetTimeEntry(_Record):
    operation: Literal["get_time_entry"] = Field("get_time_entry", title="Get Time Entry", json_schema_extra={"ui:hidden": True})


class ListResources(_Query):
    operation: Literal["list_resources"] = Field("list_resources", title="List Resources", json_schema_extra={"ui:hidden": True})


class GetResource(_Record):
    operation: Literal["get_resource"] = Field("get_resource", title="Get Resource", json_schema_extra={"ui:hidden": True})


class CreateTicket(_Dates):
    operation: Literal["create_ticket"] = Field("create_ticket", title="Create Ticket", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., ge=1, title="Company Id")
    title: str = Field(..., min_length=1, max_length=255, title="Title")
    priority: int = Field(..., ge=1, title="Priority")
    status: int = Field(..., ge=1, title="Status")
    due_date_time: str = Field(..., title="Due Date Time")
    description: str | None = Field(None, max_length=32000, title="Description")
    contact_id: int | None = Field(None, ge=1, title="Contact Id")
    queue_id: int | None = Field(None, ge=1, title="Queue Id")
    assigned_resource_id: int | None = Field(None, ge=1, title="Assigned Resource Id")
    assigned_resource_role_id: int | None = Field(None, ge=1, title="Assigned Resource Role Id")
    resolution: str | None = Field(None, max_length=32000, title="Resolution")


class UpdateTicket(_Patch, _Dates):
    operation: Literal["update_ticket"] = Field("update_ticket", title="Update Ticket", json_schema_extra={"ui:hidden": True})
    company_id: int | None = Field(None, ge=1, title="Company Id")
    title: str | None = Field(None, min_length=1, max_length=255, title="Title")
    priority: int | None = Field(None, ge=1, title="Priority")
    status: int | None = Field(None, ge=1, title="Status")
    due_date_time: str | None = Field(None, title="Due Date Time")
    description: str | None = Field(None, max_length=32000, title="Description")
    contact_id: int | None = Field(None, ge=1, title="Contact Id")
    queue_id: int | None = Field(None, ge=1, title="Queue Id")
    assigned_resource_id: int | None = Field(None, ge=1, title="Assigned Resource Id")
    assigned_resource_role_id: int | None = Field(None, ge=1, title="Assigned Resource Role Id")
    resolution: str | None = Field(None, max_length=32000, title="Resolution")


class CreateCompany(_Input):
    operation: Literal["create_company"] = Field("create_company", title="Create Company", json_schema_extra={"ui:hidden": True})
    company_name: str = Field(..., min_length=1, max_length=100, title="Company Name")
    company_type: int = Field(..., ge=1, title="Company Type")
    owner_resource_id: int = Field(..., ge=1, title="Owner Resource Id")
    phone: str = Field(..., min_length=1, max_length=25, title="Phone")
    is_active: bool | None = Field(None, title="Is Active")
    address1: str | None = Field(None, max_length=150, title="Address1")
    city: str | None = Field(None, max_length=50, title="City")
    state: str | None = Field(None, max_length=128, title="State")
    postal_code: str | None = Field(None, max_length=50, title="Postal Code")
    web_address: str | None = Field(None, max_length=255, title="Web Address")


class UpdateCompany(_Patch):
    operation: Literal["update_company"] = Field("update_company", title="Update Company", json_schema_extra={"ui:hidden": True})
    company_name: str | None = Field(None, min_length=1, max_length=100, title="Company Name")
    company_type: int | None = Field(None, ge=1, title="Company Type")
    owner_resource_id: int | None = Field(None, ge=1, title="Owner Resource Id")
    phone: str | None = Field(None, min_length=1, max_length=25, title="Phone")
    is_active: bool | None = Field(None, title="Is Active")
    address1: str | None = Field(None, max_length=150, title="Address1")
    city: str | None = Field(None, max_length=50, title="City")
    state: str | None = Field(None, max_length=128, title="State")
    postal_code: str | None = Field(None, max_length=50, title="Postal Code")
    web_address: str | None = Field(None, max_length=255, title="Web Address")


class CreateContact(_Input):
    operation: Literal["create_contact"] = Field("create_contact", title="Create Contact", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., ge=1, title="Company Id")
    first_name: str = Field(..., min_length=1, max_length=20, title="First Name")
    last_name: str = Field(..., min_length=1, max_length=20, title="Last Name")
    is_active: int = Field(1, ge=0, le=1, title="Is Active")
    email_address: str | None = Field(None, max_length=50, title="Email Address")
    phone: str | None = Field(None, max_length=25, title="Phone")
    title: str | None = Field(None, max_length=50, title="Title")


class UpdateContact(_Patch):
    operation: Literal["update_contact"] = Field("update_contact", title="Update Contact", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., ge=1, title="Company Id")
    first_name: str | None = Field(None, min_length=1, max_length=20, title="First Name")
    last_name: str | None = Field(None, min_length=1, max_length=20, title="Last Name")
    is_active: int | None = Field(None, ge=0, le=1, title="Is Active")
    email_address: str | None = Field(None, max_length=50, title="Email Address")
    phone: str | None = Field(None, max_length=25, title="Phone")
    title: str | None = Field(None, max_length=50, title="Title")


class CreateTimeEntry(_Dates):
    operation: Literal["create_time_entry"] = Field("create_time_entry", title="Create Time Entry", json_schema_extra={"ui:hidden": True})
    ticket_id: int = Field(..., ge=1, title="Ticket Id")
    resource_id: int = Field(..., ge=1, title="Resource Id")
    role_id: int = Field(..., ge=1, title="Role Id")
    date_worked: str = Field(..., title="Date Worked")
    hours_worked: float = Field(..., gt=0, le=24, title="Hours Worked")
    summary_notes: str = Field(..., min_length=1, max_length=32000, title="Summary Notes")
    billing_code_id: int | None = Field(None, ge=1, title="Billing Code Id")
    is_non_billable: bool | None = Field(None, title="Is Non Billable")
    internal_notes: str | None = Field(None, max_length=32000, title="Internal Notes")


class UpdateTimeEntry(_Patch, _Dates):
    operation: Literal["update_time_entry"] = Field("update_time_entry", title="Update Time Entry", json_schema_extra={"ui:hidden": True})
    ticket_id: int | None = Field(None, ge=1, title="Ticket Id")
    resource_id: int | None = Field(None, ge=1, title="Resource Id")
    role_id: int | None = Field(None, ge=1, title="Role Id")
    date_worked: str | None = Field(None, title="Date Worked")
    hours_worked: float | None = Field(None, gt=0, le=24, title="Hours Worked")
    summary_notes: str | None = Field(None, min_length=1, max_length=32000, title="Summary Notes")
    billing_code_id: int | None = Field(None, ge=1, title="Billing Code Id")
    is_non_billable: bool | None = Field(None, title="Is Non Billable")
    internal_notes: str | None = Field(None, max_length=32000, title="Internal Notes")


class ListTicketNotes(_Input):
    operation: Literal["list_ticket_notes"] = Field("list_ticket_notes", title="List Ticket Notes", json_schema_extra={"ui:hidden": True})
    ticket_id: int = Field(..., ge=1, title="Ticket ID")


class CreateTicketNote(_Input):
    operation: Literal["create_ticket_note"] = Field("create_ticket_note", title="Create Ticket Note", json_schema_extra={"ui:hidden": True})
    ticket_id: int = Field(..., ge=1, title="Ticket ID")
    title: str = Field(..., min_length=1, max_length=250, title="Title")
    description: str = Field(..., min_length=1, max_length=32000, title="Description")
    note_type: int = Field(..., ge=1, title="Note type", description="Use an active noteType picklist ID from your Autotask account.")
    publish: int = Field(..., ge=1, title="Publish visibility", description="Use the publish picklist ID for the intended visibility. This may expose the note to customers.")


AutotaskConfig = Annotated[Union[
    ListTickets,
    GetTicket,
    ListCompanies,
    GetCompany,
    ListContacts,
    GetContact,
    ListTimeEntries,
    GetTimeEntry,
    ListResources,
    GetResource,
    CreateTicket,
    UpdateTicket,
    CreateCompany,
    UpdateCompany,
    CreateContact,
    UpdateContact,
    CreateTimeEntry,
    UpdateTimeEntry,
    ListTicketNotes,
    CreateTicketNote
], Field(discriminator="operation")]


class AutotaskFullConfig(NodeConfig[AutotaskConfig, AutotaskAPIKeyCredential]):
    pass


ROUTES = {'list_tickets': ('POST', '/V1.0/Tickets/query', 'list'),
 'get_ticket': ('GET', '/V1.0/Tickets/{id}', 'item'),
 'list_companies': ('POST', '/V1.0/Companies/query', 'list'),
 'get_company': ('GET', '/V1.0/Companies/{id}', 'item'),
 'list_contacts': ('POST', '/V1.0/Contacts/query', 'list'),
 'get_contact': ('GET', '/V1.0/Contacts/{id}', 'item'),
 'list_time_entries': ('POST', '/V1.0/TimeEntries/query', 'list'),
 'get_time_entry': ('GET', '/V1.0/TimeEntries/{id}', 'item'),
 'list_resources': ('POST', '/V1.0/Resources/query', 'list'),
 'get_resource': ('GET', '/V1.0/Resources/{id}', 'item'),
 'create_ticket': ('POST', '/V1.0/Tickets', 'write'),
 'update_ticket': ('PATCH', '/V1.0/Tickets', 'write'),
 'create_company': ('POST', '/V1.0/Companies', 'write'),
 'update_company': ('PATCH', '/V1.0/Companies', 'write'),
 'create_contact': ('POST', '/V1.0/Companies/{company_id}/Contacts', 'write'),
 'update_contact': ('PATCH', '/V1.0/Companies/{company_id}/Contacts', 'write'),
 'create_time_entry': ('POST', '/V1.0/TimeEntries', 'write'),
 'update_time_entry': ('PATCH', '/V1.0/TimeEntries', 'write'),
 'list_ticket_notes': ('GET', '/V1.0/Tickets/{ticket_id}/Notes', 'list'),
 'create_ticket_note': ('POST', '/V1.0/Tickets/{ticket_id}/Notes', 'write')}
WIRE_FIELDS = {'company_id': 'companyID',
 'title': 'title',
 'priority': 'priority',
 'status': 'status',
 'due_date_time': 'dueDateTime',
 'description': 'description',
 'contact_id': 'contactID',
 'queue_id': 'queueID',
 'assigned_resource_id': 'assignedResourceID',
 'assigned_resource_role_id': 'assignedResourceRoleID',
 'resolution': 'resolution',
 'company_name': 'companyName',
 'company_type': 'companyType',
 'owner_resource_id': 'ownerResourceID',
 'phone': 'phone',
 'is_active': 'isActive',
 'address1': 'address1',
 'city': 'city',
 'state': 'state',
 'postal_code': 'postalCode',
 'web_address': 'webAddress',
 'first_name': 'firstName',
 'last_name': 'lastName',
 'email_address': 'emailAddress',
 'ticket_id': 'ticketID',
 'resource_id': 'resourceID',
 'role_id': 'roleID',
 'date_worked': 'dateWorked',
 'hours_worked': 'hoursWorked',
 'summary_notes': 'summaryNotes',
 'billing_code_id': 'billingCodeID',
 'is_non_billable': 'isNonBillable',
 'internal_notes': 'internalNotes',
 'note_type': 'noteType',
 'publish': 'publish',
 'id': 'id'}


def _redact(value, credential):
    secrets = (credential.secret, credential.api_integration_code)
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(v, credential) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, credential) for k, v in value.items()}
    return value


class AutotaskNode(WorkflowNode):
    integration_type = "automation-autotask"
    connection_evidence = ConnectionEvidence(operation="list_companies", noun="companies", label_keys=("companyName", "id"))

    @classmethod
    def get_config_model(cls):
        return AutotaskFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect an Autotask API user")
        method, template, kind = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        path = template.format(**values)
        body = None
        if isinstance(config, _Query):
            body = {"maxRecords": config.max_records, "filter": json.loads(config.filter_json)}
        elif kind == "write":
            body = {WIRE_FIELDS[k]: v for k, v in values.items()
                if k != "operation" and not (config.operation == "update_contact" and k == "company_id")}
        # Fixed routes and provider-owned origins only. Do not follow paging URLs
        # or redirects with the API user's credentials. No automatic write retry.
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, credential.api_base_url + path,
                headers={"UserName": credential.username, "Secret": credential.secret,
                    "ApiIntegrationCode": credential.api_integration_code, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        if response.status_code != 200:
            message = "Autotask request failed"
            try:
                errors = response.json().get("errors")
                if isinstance(errors, list) and all(isinstance(e, str) for e in errors):
                    message = "; ".join(errors)[:4000]
            except (ValueError, AttributeError):
                pass
            return {"status": "error", "http_status": response.status_code, "error": _redact(message, credential)}
        if len(response.content) > 10_000_000:
            raise ValueError("Autotask response exceeds 10 MB; reduce maximum records")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected an Autotask JSON object")
        if data.get("errors"):
            return {"status": "error", "error": _redact(data["errors"], credential)}
        if kind == "write":
            item_id = data.get("itemId")
            if type(item_id) is not int or item_id <= 0:
                raise ValueError("Autotask did not confirm a record ID")
            return {"status": "success", "item_id": item_id}
        if kind == "item":
            item = data.get("item")
            if not isinstance(item, dict) or type(item.get("id")) is not int or item["id"] != config.id:
                raise ValueError("Autotask returned a missing or different record")
            return {"status": "success", "item": _redact(item, credential)}
        items = data.get("items")
        details = data.get("pageDetails")
        if (not isinstance(items, list) or not isinstance(details, dict)
                or any(not isinstance(item, dict) or type(item.get("id")) is not int for item in items)):
            raise ValueError("Autotask returned an invalid page")
        if "nextPageUrl" not in details:
            raise ValueError("Autotask page omitted its continuation state")
        next_url = details["nextPageUrl"]
        if next_url is not None and (not isinstance(next_url, str) or not next_url):
            raise ValueError("Autotask returned an invalid continuation")
        has_more = next_url is not None
        if has_more and not items:
            raise ValueError("Autotask returned an empty page with a continuation")
        if config.operation == "list_ticket_notes" and any(item.get("ticketID") != config.ticket_id for item in items):
            raise ValueError("Autotask returned a note for a different ticket")
        return {"status": "success", "items": _redact(items, credential), "has_more": has_more,
            "next_after_id": max((item["id"] for item in items), default=None) if has_more and isinstance(config, _Query) else None,
            "page_details": _redact(details, credential)}
