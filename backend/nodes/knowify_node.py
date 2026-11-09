"""Knowify v2 operations: https://developer.knowify.com/api-docs/v2-json."""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE_URL = "https://developer.knowify.com/api/v2"


class _Config(BaseModel):
    model_config = ConfigDict(
        extra="forbid", hide_input_in_errors=True, allow_inf_nan=False
    )


class KnowifySessionToken(_Config):
    model_config = ConfigDict(
        title="Knowify Session Token",
        extra="forbid",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.knowify.com/api-docs/v2#tag/Auth/operation/login",
            "x-credential-instructions": "Obtain a kAuth session token using Knowify's documented login endpoint. Paste kauthToken without the kauth prefix. Advisor accounts must first choose a tenant through advisor-assume. Tokens expire; replace an expired token here.",
        },
    )
    credential_type: Literal["knowify_session_token"] = Field(
        "knowify_session_token", json_schema_extra={"ui:hidden": True}
    )
    session_token: str = Field(
        ...,
        min_length=1,
        max_length=16384,
        title="Session Token",
        repr=False,
        description="Your tenant-scoped Knowify kauthToken, without an Authorization prefix.",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("session_token")
    @classmethod
    def token(cls, value):
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError(
                "Paste only the kAuth token, without a prefix or whitespace"
            )
        return value


class _Page(_Config):
    limit: int = Field(50, ge=1, le=200, description="Maximum records in this page.")
    offset: int = Field(
        0,
        ge=0,
        le=9007199254740991,
        description="Rows to skip. Use next_offset for the next page.",
    )


class _Record(_Config):
    record_id: int = Field(..., ge=1, le=9007199254740991, title="Record ID")


class _Update(_Record):
    @model_validator(mode="after")
    def changes(self):
        if not any(
            v is not None
            for k, v in self.model_dump().items()
            if k not in {"operation", "record_id"}
        ):
            raise ValueError("Supply at least one field to update")
        return self


class ListClients(_Page):
    operation: Literal["list_clients"] = Field("list_clients", title="List Clients")


class GetClient(_Record):
    operation: Literal["get_client"] = Field("get_client", title="Get Client")


class CreateClient(_Config):
    operation: Literal["create_client"] = Field("create_client", title="Create Client")
    client_name: str = Field(..., min_length=1, max_length=10000)
    email: str | None = Field(None, min_length=1, max_length=10000)
    phone_number: str | None = Field(None, min_length=1, max_length=10000)
    notes: str | None = Field(None, min_length=1, max_length=10000)


class UpdateClient(_Update):
    operation: Literal["update_client"] = Field("update_client", title="Update Client")
    client_name: str | None = Field(None, min_length=1, max_length=10000)
    email: str | None = Field(None, min_length=1, max_length=10000)
    phone_number: str | None = Field(None, min_length=1, max_length=10000)
    notes: str | None = Field(None, min_length=1, max_length=10000)


class ListProjects(_Page):
    operation: Literal["list_projects"] = Field("list_projects", title="List Projects")


class GetProject(_Record):
    operation: Literal["get_project"] = Field("get_project", title="Get Project")


class CreateProject(_Config):
    operation: Literal["create_project"] = Field(
        "create_project", title="Create Project"
    )
    project_name: str = Field(..., min_length=1, max_length=10000)
    client_id: int = Field(..., ge=1, le=9007199254740991)
    project_number: str | None = Field(None, min_length=1, max_length=10000)
    budget_amount: float | None = Field(None)


class UpdateProject(_Update):
    operation: Literal["update_project"] = Field(
        "update_project", title="Update Project"
    )
    project_name: str | None = Field(None, min_length=1, max_length=10000)
    client_id: int | None = Field(None, ge=1, le=9007199254740991)
    project_number: str | None = Field(None, min_length=1, max_length=10000)
    budget_amount: float | None = Field(None)


class ListVendors(_Page):
    operation: Literal["list_vendors"] = Field("list_vendors", title="List Vendors")


class GetVendor(_Record):
    operation: Literal["get_vendor"] = Field("get_vendor", title="Get Vendor")


class CreateVendor(_Config):
    operation: Literal["create_vendor"] = Field("create_vendor", title="Create Vendor")
    vendor_name: str = Field(..., min_length=1, max_length=10000)
    email: str | None = Field(None, min_length=1, max_length=10000)
    phone_number: str | None = Field(None, min_length=1, max_length=10000)
    notes: str | None = Field(None, min_length=1, max_length=10000)


class UpdateVendor(_Update):
    operation: Literal["update_vendor"] = Field("update_vendor", title="Update Vendor")
    vendor_name: str | None = Field(None, min_length=1, max_length=10000)
    email: str | None = Field(None, min_length=1, max_length=10000)
    phone_number: str | None = Field(None, min_length=1, max_length=10000)
    notes: str | None = Field(None, min_length=1, max_length=10000)


class ListTasks(_Page):
    operation: Literal["list_tasks"] = Field("list_tasks", title="List Tasks")


class GetTask(_Record):
    operation: Literal["get_task"] = Field("get_task", title="Get Task")


class CreateTask(_Config):
    operation: Literal["create_task"] = Field("create_task", title="Create Task")
    milestone_id: int = Field(..., ge=1, le=9007199254740991)
    description: str = Field(..., min_length=1, max_length=10000)
    priority: bool | None = Field(None)
    num_days: float | None = Field(None)


class UpdateTask(_Update):
    operation: Literal["update_task"] = Field("update_task", title="Update Task")
    milestone_id: int | None = Field(None, ge=1, le=9007199254740991)
    description: str | None = Field(None, min_length=1, max_length=10000)
    priority: bool | None = Field(None)
    num_days: float | None = Field(None)


class ListInvoices(_Page):
    operation: Literal["list_invoices"] = Field("list_invoices", title="List Invoices")


class GetInvoice(_Record):
    operation: Literal["get_invoice"] = Field("get_invoice", title="Get Invoice")


class CreateInvoice(_Config):
    operation: Literal["create_invoice"] = Field(
        "create_invoice", title="Create Invoice"
    )
    client_id: int = Field(..., ge=1, le=9007199254740991)
    project_id: int | None = Field(None, ge=1, le=9007199254740991)
    invoice_number: str | None = Field(None, min_length=1, max_length=10000)
    total_amount: float | None = Field(None)
    header_text: str | None = Field(None, min_length=1, max_length=10000)


class UpdateInvoice(_Update):
    operation: Literal["update_invoice"] = Field(
        "update_invoice", title="Update Invoice"
    )
    client_id: int | None = Field(None, ge=1, le=9007199254740991)
    project_id: int | None = Field(None, ge=1, le=9007199254740991)
    invoice_number: str | None = Field(None, min_length=1, max_length=10000)
    total_amount: float | None = Field(None)
    header_text: str | None = Field(None, min_length=1, max_length=10000)


class ListBills(_Page):
    operation: Literal["list_bills"] = Field("list_bills", title="List Bills")


class ListTimeEntries(_Page):
    operation: Literal["list_time_entries"] = Field(
        "list_time_entries", title="List Time Entries"
    )


class ListPurchases(_Page):
    operation: Literal["list_purchases"] = Field(
        "list_purchases", title="List Purchases"
    )


class ListContacts(_Page):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts")


class GetCompany(_Config):
    operation: Literal["get_company"] = Field("get_company", title="Get Company")


Operation = Annotated[
    Union[
        ListClients,
        GetClient,
        CreateClient,
        UpdateClient,
        ListProjects,
        GetProject,
        CreateProject,
        UpdateProject,
        ListVendors,
        GetVendor,
        CreateVendor,
        UpdateVendor,
        ListTasks,
        GetTask,
        CreateTask,
        UpdateTask,
        ListInvoices,
        GetInvoice,
        CreateInvoice,
        UpdateInvoice,
        ListBills,
        ListTimeEntries,
        ListPurchases,
        ListContacts,
        GetCompany,
    ],
    Field(discriminator="operation"),
]


class KnowifyConfig(NodeConfig[Operation, KnowifySessionToken]):
    pass


ROUTES = {
    "list_clients": ("GET", "/clients", "client"),
    "get_client": ("GET", "/clients/{id}", "client"),
    "create_client": ("POST", "/clients", "client"),
    "update_client": ("PATCH", "/clients/{id}", "client"),
    "list_projects": ("GET", "/projects", "project"),
    "get_project": ("GET", "/projects/{id}", "project"),
    "create_project": ("POST", "/projects", "project"),
    "update_project": ("PATCH", "/projects/{id}", "project"),
    "list_vendors": ("GET", "/vendors", "vendor"),
    "get_vendor": ("GET", "/vendors/{id}", "vendor"),
    "create_vendor": ("POST", "/vendors", "vendor"),
    "update_vendor": ("PATCH", "/vendors/{id}", "vendor"),
    "list_tasks": ("GET", "/tasks", "task"),
    "get_task": ("GET", "/tasks/{id}", "task"),
    "create_task": ("POST", "/tasks", "task"),
    "update_task": ("PATCH", "/tasks/{id}", "task"),
    "list_invoices": ("GET", "/invoices", "invoice"),
    "get_invoice": ("GET", "/invoices/{id}", "invoice"),
    "create_invoice": ("POST", "/invoices", "invoice"),
    "update_invoice": ("PATCH", "/invoices/{id}", "invoice"),
    "list_bills": ("GET", "/bills", "bills"),
    "list_time_entries": ("GET", "/time-entries", "time_entries"),
    "list_purchases": ("GET", "/purchases", "purchases"),
    "list_contacts": ("GET", "/contacts", "contacts"),
    "get_company": ("GET", "/company", "company"),
}
BODY_FIELDS = {
    "client": {
        "client_name": "ClientName",
        "email": "Email",
        "phone_number": "PhoneNumber",
        "notes": "Notes",
    },
    "project": {
        "project_name": "ProjectName",
        "client_id": "ClientId",
        "project_number": "ProjectNumber",
        "budget_amount": "BudgetAmount",
    },
    "vendor": {
        "vendor_name": "VendorName",
        "email": "Email",
        "phone_number": "PhoneNumber",
        "notes": "Notes",
    },
    "task": {
        "milestone_id": "MilestoneId",
        "description": "Description",
        "priority": "Priority",
        "num_days": "NumDays",
    },
    "invoice": {
        "client_id": "ClientId",
        "project_id": "ProjectId",
        "invoice_number": "InvoiceNumber",
        "total_amount": "TotalAmount",
        "header_text": "HeaderText",
    },
}


class KnowifyNode(WorkflowNode):
    integration_type = "automation-knowify"
    connection_evidence = ConnectionEvidence(
        operation="list_projects",
        noun="Knowify projects",
        label_keys=("ProjectName", "ProjectNumber", "Id"),
    )

    @classmethod
    def get_config_model(cls):
        return KnowifyConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a Knowify session token")
        method, path, resource = ROUTES[config.operation]
        if isinstance(config, _Record):
            path = path.format(id=config.record_id)
        params = (
            {"limit": config.limit, "offset": config.offset}
            if isinstance(config, _Page)
            else {}
        )
        body = None
        if method in {"POST", "PATCH"}:
            body = {
                wire: getattr(config, field)
                for field, wire in BODY_FIELDS[resource].items()
                if getattr(config, field) is not None
            }
        async with guarded_async_client(
            timeout=30, trust_env=False, follow_redirects=False
        ) as client:
            response = await client.request(
                method,
                BASE_URL + path,
                headers={
                    "Authorization": "kauth " + credential.session_token,
                    "Accept": "application/json",
                },
                params=params,
                **({"json": body} if body is not None else {}),
            )
        response.raise_for_status()
        expected = 201 if method == "POST" else 200
        if response.status_code != expected:
            raise ValueError("Knowify did not return the documented completion status")
        if (
            len(response.content) > 10_000_000
            or response.headers.get("content-type", "").split(";")[0].strip()
            != "application/json"
        ):
            raise ValueError("Expected a bounded Knowify JSON response")
        data = response.json()
        if (
            not isinstance(data, dict)
            or data.get("error")
            or data.get("didSucceed") is False
        ):
            raise ValueError("Knowify returned an invalid response")
        if isinstance(config, _Page):
            rows, meta = data.get("data"), data.get("meta")
            if (
                not isinstance(rows, list)
                or not isinstance(meta, dict)
                or any(not isinstance(row, dict) for row in rows)
            ):
                raise ValueError("Knowify list response is missing data or meta")
            if type(meta.get("has_more")) is not bool:
                raise ValueError("Knowify list response is missing has_more")
            return {
                "status": "success",
                "data": rows,
                "meta": meta,
                "next_offset": config.offset + config.limit
                if meta["has_more"]
                else None,
            }
        return {"status": "success", "data": data}
