"""Tave (VSCO Workspace) v2 studio automation using a pasted API key.

Contract: https://workspace.vsco.co/api/v2/openapi.json, v2.0.0.
Each operation makes one request; collections preserve the provider's page metadata.
"""
from __future__ import annotations

from datetime import date as Date, time
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://workspace.vsco.co/api/v2"
Identifier = Annotated[str, Field(pattern=r"^[0-7][0-9a-hjkmnp-tv-z]{25}$", description="Lowercase Tave ULID.")]


class TaveAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Tave API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://workspace.vsco.co/settings/api",
        "x-credential-instructions": "In Tave (VSCO Workspace), open Settings → API and copy an API key for your studio. Paste the key without a header prefix. Enable write access for operations that create or update records.",
    })
    credential_type: Literal["tave_api_key"] = Field("tave_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, title="Page")
    page_size: int = Field(100, ge=10, le=100, title="Page Size",
                           description="One page per run; use meta.totalPages to request subsequent pages.")


class _JobFilter(_Page):
    job_id: Identifier | None = Field(None, title="Job ID")


class GetStudio(_Input):
    operation: Literal["get_studio"] = Field("get_studio", title="Get Studio", json_schema_extra={"ui:hidden": True})


class ListContacts(_Page):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})
    email: str | None = Field(None, title="Email Filter", max_length=255)
    include_hidden: bool = False


class GetContact(_Input):
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})
    contact_id: Identifier


class _Person(_Input):
    first_name: str | None = Field(None, max_length=48)
    last_name: str | None = Field(None, max_length=48)
    email: str | None = Field(None, max_length=255, json_schema_extra={"format": "email"})
    company_name: str | None = Field(None, max_length=128)
    job_title: str | None = Field(None, max_length=64)


class CreateContact(_Person):
    operation: Literal["create_contact"] = Field("create_contact", title="Create Person Contact", json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., min_length=1, max_length=48)


class UpdateContact(_Person):
    operation: Literal["update_contact"] = Field("update_contact", title="Update Person Contact", description="Use the ID of a person contact, not a company or location.", json_schema_extra={"ui:hidden": True})
    contact_id: Identifier


class ListJobs(_Page):
    operation: Literal["list_jobs"] = Field("list_jobs", title="List Jobs", json_schema_extra={"ui:hidden": True})
    include_closed: bool = False
    stage: Literal["lead", "booked", "fulfillment", "completed"] | None = None
    lead_status_id: Identifier | None = None
    event_date_from: Date | None = None
    event_date_to: Date | None = None


class GetJob(_Input):
    operation: Literal["get_job"] = Field("get_job", title="Get Job", json_schema_extra={"ui:hidden": True})
    job_id: Identifier


class _Job(_Input):
    name: str | None = Field(None, max_length=255)
    stage: Literal["lead", "booked", "fulfillment", "completed"] | None = None
    event_date: Date | None = None
    job_type_id: Identifier | None = None
    lead_status_id: Identifier | None = None
    lead_source_id: Identifier | None = None
    lead_notes: str | None = Field(None, max_length=100000, json_schema_extra={"ui:widget": "textarea"})
    closed: bool | None = None


class CreateJob(_Job):
    operation: Literal["create_job"] = Field("create_job", title="Create Job", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    stage: Literal["lead", "booked", "fulfillment", "completed"] = "lead"


class UpdateJob(_Job):
    operation: Literal["update_job"] = Field("update_job", title="Update Job", json_schema_extra={"ui:hidden": True})
    job_id: Identifier


class ListEvents(_JobFilter):
    operation: Literal["list_events"] = Field("list_events", title="List Events", json_schema_extra={"ui:hidden": True})
    occurs_from: Date | None = None
    occurs_to: Date | None = None


class GetEvent(_Input):
    operation: Literal["get_event"] = Field("get_event", title="Get Event", json_schema_extra={"ui:hidden": True})
    event_id: Identifier


class _Event(_Input):
    name: str | None = Field(None, max_length=255)
    job_id: Identifier | None = None
    type_id: Identifier | None = Field(None, title="Event Type ID")
    start_date: Date | None = None
    start_time: time | None = None
    end_date: Date | None = None
    end_time: time | None = None
    timezone_name: str | None = Field(None, max_length=255)
    all_day: bool | None = None
    confirmed: bool | None = None
    description_html: str | None = Field(None, max_length=100000, json_schema_extra={"ui:widget": "textarea"})


class CreateEvent(_Event):
    operation: Literal["create_event"] = Field("create_event", title="Create Event", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)


class UpdateEvent(_Event):
    operation: Literal["update_event"] = Field("update_event", title="Update Event", json_schema_extra={"ui:hidden": True})
    event_id: Identifier


class ListTasks(_JobFilter):
    operation: Literal["list_tasks"] = Field("list_tasks", title="List Tasks", json_schema_extra={"ui:hidden": True})
    task_list_id: Identifier | None = None
    user_id: Identifier | None = None
    completed: bool | None = None


class GetTask(_Input):
    operation: Literal["get_task"] = Field("get_task", title="Get Task", json_schema_extra={"ui:hidden": True})
    task_id: Identifier


class _Task(_Input):
    name: str = Field(..., min_length=1, max_length=128)
    task_list_id: Identifier
    job_id: Identifier | None = None
    due_date: Date | None = None
    user_id: Identifier | None = None
    completed: bool | None = None


class CreateTask(_Task):
    operation: Literal["create_task"] = Field("create_task", title="Create Task", json_schema_extra={"ui:hidden": True})


class UpdateTask(_Task):
    operation: Literal["update_task"] = Field("update_task", title="Update Task", description="Supply the required name and task list along with the changes.", json_schema_extra={"ui:hidden": True})
    task_id: Identifier


class ListNotes(_JobFilter):
    operation: Literal["list_notes"] = Field("list_notes", title="List Notes", json_schema_extra={"ui:hidden": True})


class CreateNote(_Input):
    operation: Literal["create_note"] = Field("create_note", title="Create Note", json_schema_extra={"ui:hidden": True})
    content_html: str = Field(..., min_length=1, max_length=100000, json_schema_extra={"ui:widget": "textarea"})
    job_id: Identifier | None = None
    contact_id: Identifier | None = None
    date: Date | None = None


class ListInvoices(_JobFilter):
    operation: Literal["list_invoices"] = Field("list_invoices", title="List Invoices", json_schema_extra={"ui:hidden": True})
    invoice_status: Literal["draft", "open", "paid-in-full", "voided"] | None = Field(None, title="Invoice Status")
    due_from: Date | None = None
    due_to: Date | None = None
    past_due: bool = False
    include_voided: bool = False


class GetInvoice(_Input):
    operation: Literal["get_invoice"] = Field("get_invoice", title="Get Invoice", json_schema_extra={"ui:hidden": True})
    invoice_id: Identifier


class ListOrders(_Page):
    operation: Literal["list_orders"] = Field("list_orders", title="List Orders", json_schema_extra={"ui:hidden": True})


class GetOrder(_Input):
    operation: Literal["get_order"] = Field("get_order", title="Get Order", json_schema_extra={"ui:hidden": True})
    order_id: Identifier


class ListLeadStatuses(_Page):
    operation: Literal["list_lead_statuses"] = Field("list_lead_statuses", title="List Lead Statuses", json_schema_extra={"ui:hidden": True})


class ListJobTypes(_Page):
    operation: Literal["list_job_types"] = Field("list_job_types", title="List Job Types", json_schema_extra={"ui:hidden": True})


TaveOperation = Annotated[Union[
    GetStudio, ListContacts, GetContact, CreateContact, UpdateContact,
    ListJobs, GetJob, CreateJob, UpdateJob, ListEvents, GetEvent, CreateEvent, UpdateEvent,
    ListTasks, GetTask, CreateTask, UpdateTask, ListNotes, CreateNote,
    ListInvoices, GetInvoice, ListOrders, GetOrder, ListLeadStatuses, ListJobTypes,
], Field(discriminator="operation")]


class TaveConfig(NodeConfig[TaveOperation, TaveAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Explicit provider routes; config cannot supply a method, host, or arbitrary path.
ROUTES = {
    "get_studio": ("GET", "/studio/me", None),
    "list_contacts": ("GET", "/address-book", None),
    "get_contact": ("GET", "/address-book/{contact_id}", "contact_id"),
    "create_contact": ("POST", "/address-book", None),
    "update_contact": ("PUT", "/address-book/{contact_id}", "contact_id"),
    "list_jobs": ("GET", "/job", None),
    "get_job": ("GET", "/job/{job_id}", "job_id"),
    "create_job": ("POST", "/job", None),
    "update_job": ("PUT", "/job/{job_id}", "job_id"),
    "list_events": ("GET", "/event", None),
    "get_event": ("GET", "/event/{event_id}", "event_id"),
    "create_event": ("POST", "/event", None),
    "update_event": ("PUT", "/event/{event_id}", "event_id"),
    "list_tasks": ("GET", "/task", None),
    "get_task": ("GET", "/task/{task_id}", "task_id"),
    "create_task": ("POST", "/task", None),
    "update_task": ("PUT", "/task/{task_id}", "task_id"),
    "list_notes": ("GET", "/note", None),
    "create_note": ("POST", "/note", None),
    "list_invoices": ("GET", "/invoice", None),
    "get_invoice": ("GET", "/invoice/{invoice_id}", "invoice_id"),
    "list_orders": ("GET", "/order", None),
    "get_order": ("GET", "/order/{order_id}", "order_id"),
    "list_lead_statuses": ("GET", "/lead-status", None),
    "list_job_types": ("GET", "/job-type", None),
}


def _wire(key):
    if key == "invoice_status":
        return "status"
    head, *tail = key.split("_")
    return head + "".join(part.title() for part in tail)


class TaveNode(WorkflowNode):
    integration_type = "automation-tave"
    connection_evidence = ConnectionEvidence(identity_operation="get_studio", noun="Tave studio")

    @classmethod
    def get_config_model(cls):
        return TaveConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Tave API key")
        op = self.config.config
        method, path, identifier = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if identifier:
            path = path.replace("{" + identifier + "}", quote(values.pop(identifier), safe=""))
        payload = {_wire(k): v for k, v in values.items()}
        if method != "GET" and op.operation in {"create_contact", "update_contact"}:
            payload["kind"] = "person"
        if method == "GET":
            payload = {k: str(v).lower() if isinstance(v, bool) else v for k, v in payload.items()}
        token = self.config.credentials.api_key
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                headers={"X-API-KEY": token, "Accept": "application/json"},
                **({"params": payload} if method == "GET" else {"json": payload}))
        if not 200 <= response.status_code < 300:
            message = "Tave request failed"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"][:2000].replace(token, "[redacted]")
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": message}
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Expected a Tave JSON object")
        if "error" in result or "errors" in result:
            return {"status": "error", "error": "Tave returned an error envelope"}
        if op.operation.startswith("list_"):
            if not isinstance(result.get("items"), list):
                raise ValueError("Expected a Tave collection with items")
            return {**result, "status": "success"}
        return {"status": "success", "data": result}
