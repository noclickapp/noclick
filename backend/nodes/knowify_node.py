"""Knowify v2 operations: https://developer.knowify.com/api-docs/v2-json."""
import hashlib
import json

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
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


class OnNewOrUpdatedProjects(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_projects"] = Field(
        "on_new_or_updated_projects", title="On New or Updated Projects",
        json_schema_extra={"x-is-trigger": True, "x-category": "Triggers",
                           "x-display-name": "On New or Updated Projects"},
    )


class OnNewOrUpdatedClients(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_clients"] = Field(
        "on_new_or_updated_clients", title="On New or Updated Clients",
        json_schema_extra={"x-is-trigger": True, "x-category": "Triggers",
                           "x-display-name": "On New or Updated Clients"},
    )


class OnNewOrUpdatedInvoices(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_invoices"] = Field(
        "on_new_or_updated_invoices", title="On New or Updated Invoices",
        json_schema_extra={"x-is-trigger": True, "x-category": "Triggers",
                           "x-display-name": "On New or Updated Invoices"},
    )


class OnNewOrUpdatedTasks(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_tasks"] = Field(
        "on_new_or_updated_tasks", title="On New or Updated Tasks",
        json_schema_extra={"x-is-trigger": True, "x-category": "Triggers",
                           "x-display-name": "On New or Updated Tasks"},
    )


Operation = Annotated[
    Union[
        OnNewOrUpdatedProjects,
        OnNewOrUpdatedClients,
        OnNewOrUpdatedInvoices,
        OnNewOrUpdatedTasks,
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


POLL_RESOURCES = {
    "on_new_or_updated_projects": ("projects", "ProjectName"),
    "on_new_or_updated_clients": ("clients", "ClientName"),
    "on_new_or_updated_invoices": ("invoices", "InvoiceNumber"),
    "on_new_or_updated_tasks": ("tasks", "Description"),
}


class KnowifyNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-knowify"
    connection_evidence = ConnectionEvidence(
        operation="list_projects",
        noun="Knowify projects",
        label_keys=("ProjectName", "ProjectNumber", "Id"),
    )

    @classmethod
    def get_config_model(cls):
        return KnowifyConfig

    @staticmethod
    def _list_page(data):
        rows, meta = data.get("data"), data.get("meta")
        if (not isinstance(rows, list) or not isinstance(meta, dict)
                or any(not isinstance(row, dict) for row in rows)
                or type(meta.get("has_more")) is not bool):
            raise ValueError("Knowify list response is missing data or meta")
        return rows, meta

    async def _request(self, method, path, params, body=None):
        credential = self.config.credentials
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
        if not isinstance(data, dict):
            raise ValueError("Knowify returned an invalid response")
        return data

    async def _poll_changes(self, operation):
        resource, _ = POLL_RESOURCES[operation]
        records = {}
        # A complete snapshot is required before saving seen versions. Fail a
        # large/incomplete scan without consuming events; never silently truncate.
        for page in range(25):
            data = await self._request("GET", "/" + resource, {
                "limit": 200, "offset": page * 200,
                "order[0][0]": "DateModified", "order[0][1]": "DESC",
                "order[1][0]": "Id", "order[1][1]": "DESC",
            })
            rows, meta = self._list_page(data)
            for row in rows:
                if type(row.get("Id")) is not int:
                    raise ValueError("Knowify change record is missing its ID")
            total = meta.get("total")
            if type(total) is not int or total < 0:
                raise ValueError("Knowify list response is missing its total")
            if total > 5000:
                raise ValueError("Knowify polling supports at most 5,000 records per resource")
            for row in rows:
                # Offset pages can overlap when records change during the scan.
                # The newest occurrence wins, and one version emits only once.
                records.setdefault(row["Id"], row)
            if not meta["has_more"] or page * 200 + len(rows) >= total:
                break
            if not rows:
                raise ValueError("Knowify returned an empty page with more records pending")
        else:
            raise ValueError("Knowify polling supports at most 5,000 records per resource")
        fresh = await self._filter_unseen(
            list(records.values()), self._record_version
        )
        return {"status": "success", "resource": resource, "changes": fresh,
                "change_count": len(fresh)}

    @staticmethod
    def _record_version(row):
        # DateModified is nullable in Knowify's contract. A stable content hash
        # still detects edits when the provider has no modification timestamp.
        version = row.get("DateModified") or hashlib.sha256(
            json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return f"{row['Id']}:{version}"

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") in POLL_RESOURCES:
            return bool(output.get("change_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        if "changes" not in output:
            return super().resolve_agent_event(output)
        changes = output["changes"]
        if not changes:
            return None
        resource = output["resource"]
        label = next(label for name, label in POLL_RESOURCES.values() if name == resource)
        lines = []
        for row in changes[:10]:
            context = []
            if resource in {"projects", "invoices"} and row.get("ClientId") is not None:
                context.append(f"client {row['ClientId']}")
            if resource in {"invoices", "tasks"} and row.get("ProjectId") is not None:
                context.append(f"project {row['ProjectId']}")
            who = (row.get("ModifiedBy") or row.get("CreatedBy")) if resource != "projects" else None
            if who is not None:
                context.append(f"by user {who}")
            when = row.get("DateModified") or "time unavailable"
            lines.append(f"- {row.get(label) or resource.rstrip('s')} (ID {row['Id']}), "
                         f"changed {when}" + ("; " + ", ".join(context) if context else ""))
        if len(changes) > 10:
            lines.append(f"- and {len(changes) - 10} more (see changes)")
        return {"text": f"Knowify: {len(changes)} new or updated {resource}:\n" + "\n".join(lines),
                "conversation_key": None}

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a Knowify session token")
        if config.operation in POLL_RESOURCES:
            return await self._poll_changes(config.operation)
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
        data = await self._request(method, path, params, body)
        if isinstance(config, _Page):
            rows, meta = self._list_page(data)
            return {
                "status": "success",
                "data": rows,
                "meta": meta,
                "next_offset": config.offset + config.limit
                if meta["has_more"]
                else None,
            }
        return {"status": "success", "data": data}
