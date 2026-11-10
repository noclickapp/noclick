"""DoorLoop account automation with a user-supplied API key.

Actions issue one request to DoorLoop's published v1 contract. Lists return one
explicit page; new-record triggers page their creation-date scope before deduping.
Writes use typed bodies instead of arbitrary JSON.
"""
from __future__ import annotations
from datetime import date
import json
from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.doorloop.com/api"
Id = Annotated[str, Field(pattern=r"^[a-fA-F0-9]{24}$", description="DoorLoop 24-character resource ID.")]


class DoorLoopAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="DoorLoop API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://api.doorloop.com/reference/authentication",
            "x-credential-instructions": "In DoorLoop company settings, open Zapier & API Keys and create an API key. Paste only the key. Its access role must allow the resources you use. NoClick reads the user who created the key to verify the connection."})
    credential_type: Literal["doorloop_api_key"] = Field("doorloop_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", repr=False, min_length=1, max_length=8192, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page_number: int = Field(1, ge=1, description="One-based page number. Each execution retrieves one page.")
    page_size: int = Field(50, ge=1, le=1000)


class _Person(_Input):
    firstName: str = Field(..., min_length=1)
    lastName: str = Field(..., min_length=1)
    email: str | None = Field(None, description="Primary email address; mapped to DoorLoop's emails collection.")
    phone: str | None = Field(None, max_length=50, description="Mobile phone number.")
    companyName: str | None = None
    notes: str | None = None


class _InternalTask(_Input):
    type: Literal["INTERNAL_TASK"] = Field("INTERNAL_TASK", description="Create or update an internal task.")
    subject: str = Field(..., min_length=1, max_length=255)
    status: Literal["NOT_STARTED", "RECEIVED", "IN_PROGRESS", "COMPLETED", "ARCHIVED"] = "NOT_STARTED"
    requestedByUser: Id = Field(..., description="DoorLoop user requesting the internal task.")
    description: str | None = Field(None, max_length=10000)
    dueDate: date | None = None
    priority: Literal["LOW", "MEDIUM", "HIGH"] | None = None
    property: Id | None = None
    unit: Id | None = None
    assignedToUsers: list[Id] | None = None
    notifyAssignees: bool = Field(False, description="Notify assigned users when this task is created or updated.")
    entryNotes: str | None = Field(None, max_length=10000)
    entryPermission: Literal["NOT_APPLICABLE", "YES", "NO"] | None = None


class DoorLoopGetCurrentUser(_Input):
    """Read the user who created this API key."""
    operation: Literal["get_current_user"] = "get_current_user"


class DoorLoopListProperties(_Page):
    """List one page of properties."""
    operation: Literal["list_properties"] = "list_properties"
    filter_text: str | None = Field(None, description='Filter by Property Name')
    filter_group: str | None = Field(None, description='Filter by Portfolio Id')
    filter_class: Literal['RESIDENTIAL', 'COMMERCIAL'] | None = Field(None, description='Filter by Property Class')
    filter_owner: str | None = Field(None, description='Filter by Property Owner')


class DoorLoopGetProperty(_Input):
    """Retrieve one property."""
    operation: Literal["get_property"] = "get_property"
    propertyId: Id


class DoorLoopListUnits(_Page):
    """List one page of units."""
    operation: Literal["list_units"] = "list_units"
    filter_group: str | None = Field(None, description='Filters by Portfolio Id')
    filter_property: str | None = Field(None, description='Filter by Property Id')
    filter_owner: str | None = Field(None, description='Filter by Owner Id')
    filter_text: str | None = Field(None, description='Filter by Unit Name')
    filter_active: Literal['true', 'false', 'all'] | None = Field(None, description='Which units to return by status. Without this parameter only active units are returned. Use all for active and inactive units together, or false for only the inactive ones.')


class DoorLoopGetUnit(_Input):
    """Retrieve one unit."""
    operation: Literal["get_unit"] = "get_unit"
    unitId: Id


class DoorLoopListLeases(_Page):
    """List one page of leases."""
    operation: Literal["list_leases"] = "list_leases"
    filter_group: str | None = Field(None, description='Filters by Portfolio Id')
    filter_property: str | None = Field(None, description='Filter by Property Id')
    filter_owner: str | None = Field(None, description='Filter by Owner Id')
    filter_text: str | None = Field(None, description='Filter by Lease Name')
    filter_start_date_from: date | None = Field(None, description='Filter by Start Date (YYYY-MM-DD)')
    filter_start_date_to: date | None = Field(None, description='Filter by Start Date (YYYY-MM-DD)')
    filter_end_date_from: date | None = Field(None, description='Filter by End Date (YYYY-MM-DD)')
    filter_end_date_to: date | None = Field(None, description='Filter by End Date (YYYY-MM-DD)')
    filter_propertyClass: Literal['RESIDENTIAL', 'COMMERCIAL'] | None = Field(None, description='Filter by Property Class')
    filter_unit: str | None = Field(None, description='Filter by Unit Id')
    filter_tenant: str | None = Field(None, description='Filter by Tenant Id')
    filter_outstandingBalanceGreaterThan: float | None = Field(None, description='Filter by Min Outstanding Balance')
    filter_status: Literal['ACTIVE', 'INACTIVE'] | None = Field(None, description='Filter by Status')
    filter_term: Literal['Rollover', 'AtWill'] | None = Field(None, description='Filter by Term')
    filter_calculatedStatus: Literal['IN_EVICTION', 'PAY_OR_QUIT_EXPIRED', 'PAY_OR_QUIT_SENT', 'EXPIRED', 'AT_RISK', 'ACTIVE'] | None = Field(None, description='Collections stage, resolved by priority. NOTE: ACTIVE means active AND not in any collections state - it excludes pay-or-quit, holdover, on-notice and eviction leases, all of which are still occupied and paying. To list current occupants use GET /leases/tenants?filter_status=CURRENT instead.')
    filter_situation: Literal['BALANCE_DUE', 'CREDIT_AVAILABLE', 'ZERO_BALANCE', 'EXPIRED', 'EVICTION'] | None = Field(None, description='Filter by lease situation, derived from balance and lifecycle')
    filter_evictionPending: bool | None = Field(None, description='Return only leases with a pending eviction')


class DoorLoopGetLease(_Input):
    """Retrieve one lease."""
    operation: Literal["get_lease"] = "get_lease"
    leaseId: Id


class DoorLoopListTenants(_Page):
    """List one page of tenants."""
    operation: Literal["list_tenants"] = "list_tenants"
    filter_group: str | None = Field(None, description='Filter by Portfolio Id')
    filter_property: str | None = Field(None, description='Filter by Property Id')
    filter_lease: str | None = Field(None, description='Filter by Lease Id')
    filter_text: str | None = Field(None, description='Filter by Tenant Name / Email')
    filter_unit: str | None = Field(None, description='Filter by Unit Id')
    filter_type: Literal['LEASE_TENANT', 'PROSPECT_TENANT'] | None = Field(None, description='Filter by Tenant Type')


class DoorLoopGetTenant(_Input):
    """Retrieve one tenant."""
    operation: Literal["get_tenant"] = "get_tenant"
    tenantId: Id


class DoorLoopListTasks(_Page):
    """List one page of tasks."""
    operation: Literal["list_tasks"] = "list_tasks"
    filter_propertyGroup: str | None = Field(None, description='Filter by Portfolio Id')
    filter_property: str | None = Field(None, description='Filter by Property Id')
    filter_unit: str | None = Field(None, description='Filter by Unit Id')
    filter_type: Literal['INTERNAL_TASK', 'WORK_ORDER', 'TENANT_REQUEST', 'OWNER_REQUEST'] | None = Field(None, description='Filter by Task Type')
    filter_status: Literal['NOT_STARTED', 'IN_PROGRESS', 'COMPLETED', 'NOT_COMPLETED', 'RECEIVED', 'ARCHIVED'] | None = Field(None, description='Filter by Task Status')
    filter_createdAt_from: date | None = Field(None, description='Format: YYYY-MM-DD')
    filter_createdAt_to: date | None = Field(None, description='Format: YYYY-MM-DD')
    filter_dueDate_from: date | None = Field(None, description='Format: YYYY-MM-DD')
    filter_dueDate_to: date | None = Field(None, description='Format: YYYY-MM-DD')
    filter_completedAt_from: date | None = Field(None, description='Format: YYYY-MM-DD')
    filter_completedAt_to: date | None = Field(None, description='Format: YYYY-MM-DD')
    filter_assignedToUser: str | None = Field(None, description='Filter by User Id or "unassigned"')
    filter_text: str | None = Field(None, description='Filter by Subject, Description or Reference')
    filter_requestedById: str | None = Field(None, description='Filter by Requested by User, Tenant or Owner Id')


class DoorLoopGetTask(_Input):
    """Retrieve one task."""
    operation: Literal["get_task"] = "get_task"
    taskId: Id


class DoorLoopListOwners(_Page):
    """List one page of owners."""
    operation: Literal["list_owners"] = "list_owners"
    filter_group: str | None = Field(None, description='Filter by Portfolio Id')
    filter_property: str | None = Field(None, description='Filter by Property Id')
    filter_active: bool | None = Field(None, description='Filter by Active/Inactive')
    filter_text: str | None = Field(None, description='Filter by Owner Name / Email')
    filter_management_ends_before: date | None = Field(None, description='Format: YYYY-MM-DD')
    filter_createdAt_from: date | None = Field(None, description='Format: YYYY-MM-DD')
    filter_createdAt_to: date | None = Field(None, description='Format: YYYY-MM-DD')


class DoorLoopGetOwner(_Input):
    """Retrieve one owner."""
    operation: Literal["get_owner"] = "get_owner"
    ownerId: Id


class DoorLoopListVendors(_Page):
    """List one page of vendors."""
    operation: Literal["list_vendors"] = "list_vendors"
    filter_property: str | None = Field(None, description='Filter by Property Id')
    filter_active: bool | None = Field(None, description='Filter by Active/Inactive')
    filter_insurance_expires_before: date | None = Field(None, description='Format: YYYY-MM-DD')
    filter_openBalance: bool | None = Field(None, description='If true, will return only vendors with an open balance')
    filter_createdAt_from: date | None = Field(None, description='Format: YYYY-MM-DD')
    filter_createdAt_to: date | None = Field(None, description='Format: YYYY-MM-DD')


class DoorLoopGetVendor(_Input):
    """Retrieve one vendor."""
    operation: Literal["get_vendor"] = "get_vendor"
    vendorId: Id


class DoorLoopListLeasePayments(_Page):
    """List one page of lease-payments."""
    operation: Literal["list_lease_payments"] = "list_lease_payments"
    filter_lease: str | None = Field(None, description='Filter by Lease Id')
    filter_property: str | None = Field(None, description='Filter by Property Id')
    filter_paymentMethod: Literal['CASH', 'CHECK', 'CREDIT_CARD', 'CASHIERS_CHECK', 'MONEY_ORDER', 'EFT', 'DEBIT_CARD', 'OTHER', 'EPAY'] | None = Field(None, description='Filter by Payment Method')
    filter_owner: str | None = Field(None, description='Filter by Owner Id')
    filter_date_from: date | None = Field(None, description='Filter by Date (YYYY-MM-DD)')
    filter_date_to: date | None = Field(None, description='Filter by Date (YYYY-MM-DD)')


class DoorLoopGetLeasePayment(_Input):
    """Retrieve one lease payment."""
    operation: Literal["get_lease_payment"] = "get_lease_payment"
    leasePaymentId: Id


class DoorLoopListNotes(_Page):
    """List one page of notes."""
    operation: Literal["list_notes"] = "list_notes"
    filter_createdAt_from: date | None = Field(None, description='Format: YYYY-MM-DD')
    filter_createdAt_to: date | None = Field(None, description='Format: YYYY-MM-DD')
    filter_resourceId: str | None = Field(None, description='')
    filter_createdBy: str | None = Field(None, description='')
    filter_tags: str | None = Field(None, description='')
    filter_text: str | None = Field(None, description='Filter by Note Title or Body')


class DoorLoopGetNote(_Input):
    """Retrieve one note."""
    operation: Literal["get_note"] = "get_note"
    noteId: Id


class DoorLoopCreateProspect(_Person):
    """Create a prospect, which becomes a tenant when linked to a lease."""
    operation: Literal["create_prospect"] = "create_prospect"


class DoorLoopCreateOwner(_Person):
    """Create a property owner."""
    operation: Literal["create_owner"] = "create_owner"
    active: bool = True


class DoorLoopCreateTask(_InternalTask):
    """Create an internal task with an explicit requesting user."""
    operation: Literal["create_task"] = "create_task"


class DoorLoopUpdateTask(_InternalTask):
    """Update an internal task; supply its required type, subject and status."""
    operation: Literal["update_task"] = "update_task"
    taskId: Id


class DoorLoopDeleteTask(_Input):
    """Delete a task by ID."""
    operation: Literal["delete_task"] = "delete_task"
    taskId: Id


class DoorLoopCreateNote(_Input):
    """Create a note linked to a specific DoorLoop resource."""
    operation: Literal["create_note"] = "create_note"
    title: str = Field(..., min_length=1, max_length=255)
    body: str | None = Field(None, max_length=10000)
    resource_id: Id
    resource_type: Literal["TENANT", "OWNER", "VENDOR", "PROPERTY", "UNIT", "LEASE", "LEASE_DRAFT", "TASK", "RENTAL_APPLICATION"]
    tags: list[Id] | None = None


class _NewRecord(PollTriggerConfigBase):
    """Watch a creation-date scope; existing records are baselined on arming."""
    model_config = ConfigDict(extra="forbid", json_schema_extra={"x-requires-webhook": True})
    created_since: date | None = Field(None, description="Only watch records created on or after this date. Narrow this scope if it exceeds 10,000 records.")


class DoorLoopOnNewTask(_NewRecord):
    """On New Task: poll the documented creation-date-filtered list."""
    operation: Literal["on_new_task"] = Field("on_new_task", title="On New Task", json_schema_extra={
        "const": "on_new_task", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On New Task",
    })
    filter_property: Id | None = None
    filter_type: Literal["INTERNAL_TASK", "WORK_ORDER", "TENANT_REQUEST", "OWNER_REQUEST"] | None = None


class DoorLoopOnNewOwner(_NewRecord):
    """On New Owner: poll the documented creation-date-filtered list."""
    operation: Literal["on_new_owner"] = Field("on_new_owner", title="On New Owner", json_schema_extra={
        "const": "on_new_owner", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On New Owner",
    })
    filter_property: Id | None = None


class DoorLoopOnNewVendor(_NewRecord):
    """On New Vendor: poll the documented creation-date-filtered list."""
    operation: Literal["on_new_vendor"] = Field("on_new_vendor", title="On New Vendor", json_schema_extra={
        "const": "on_new_vendor", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On New Vendor",
    })
    filter_property: Id | None = None


class DoorLoopOnNewNote(_NewRecord):
    """On New Note: poll the documented creation-date-filtered list."""
    operation: Literal["on_new_note"] = Field("on_new_note", title="On New Note", json_schema_extra={
        "const": "on_new_note", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On New Note",
    })
    filter_resourceId: Id | None = None


DoorLoopConfig = Annotated[Union[
    DoorLoopOnNewTask,
    DoorLoopOnNewOwner,
    DoorLoopOnNewVendor,
    DoorLoopOnNewNote,
    DoorLoopGetCurrentUser,
    DoorLoopListProperties,
    DoorLoopGetProperty,
    DoorLoopListUnits,
    DoorLoopGetUnit,
    DoorLoopListLeases,
    DoorLoopGetLease,
    DoorLoopListTenants,
    DoorLoopGetTenant,
    DoorLoopListTasks,
    DoorLoopGetTask,
    DoorLoopListOwners,
    DoorLoopGetOwner,
    DoorLoopListVendors,
    DoorLoopGetVendor,
    DoorLoopListLeasePayments,
    DoorLoopGetLeasePayment,
    DoorLoopListNotes,
    DoorLoopGetNote,
    DoorLoopCreateProspect,
    DoorLoopCreateOwner,
    DoorLoopCreateTask,
    DoorLoopUpdateTask,
    DoorLoopDeleteTask,
    DoorLoopCreateNote,
], Field(discriminator="operation")]


class DoorLoopFullConfig(NodeConfig[DoorLoopConfig, DoorLoopAPIKeyCredential]):
    pass


ROUTES = {'get_current_user': ('GET', '/users/me'), 'list_properties': ('GET', '/properties'), 'get_property': ('GET', '/properties/{propertyId}'), 'list_units': ('GET', '/units'), 'get_unit': ('GET', '/units/{unitId}'), 'list_leases': ('GET', '/leases'), 'get_lease': ('GET', '/leases/{leaseId}'), 'list_tenants': ('GET', '/tenants'), 'get_tenant': ('GET', '/tenants/{tenantId}'), 'list_tasks': ('GET', '/tasks'), 'get_task': ('GET', '/tasks/{taskId}'), 'list_owners': ('GET', '/owners'), 'get_owner': ('GET', '/owners/{ownerId}'), 'list_vendors': ('GET', '/vendors'), 'get_vendor': ('GET', '/vendors/{vendorId}'), 'list_lease_payments': ('GET', '/lease-payments'), 'get_lease_payment': ('GET', '/lease-payments/{leasePaymentId}'), 'list_notes': ('GET', '/notes'), 'get_note': ('GET', '/notes/{noteId}'), 'create_prospect': ('POST', '/tenants'), 'create_owner': ('POST', '/owners'), 'create_task': ('POST', '/tasks'), 'update_task': ('PUT', '/tasks/{taskId}'), 'delete_task': ('DELETE', '/tasks/{taskId}'), 'create_note': ('POST', '/notes')}


class DoorLoopNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-doorloop"
    connection_evidence = ConnectionEvidence(noun="DoorLoop account", identity_operation="get_current_user", identity_keys=("loginEmail", "name", "id"))

    @classmethod
    def get_config_model(cls):
        return DoorLoopFullConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation", "").startswith("on_new_"):
            return bool(output.get("new_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or "new_records" not in output:
            return super().resolve_agent_event(output)
        records = output["new_records"]
        if not records:
            return None
        kind = output["record_type"]
        lines = []
        for record in records[:10]:
            if kind == "task":
                label = record.get("subject") or "Task"
                details = {key: record.get(key) for key in (
                    "type", "status", "description", "requestedByUser", "requestedByTenant",
                    "requestedByOwner", "property", "unit", "assignedToUsers", "workOrder")
                    if record.get(key) is not None}
            elif kind == "note":
                label = record.get("title") or "Note"
                details = {key: record.get(key) for key in ("body", "createdBy", "linkedResource")
                           if record.get(key) is not None}
            else:
                label = " ".join(value for value in (record.get("firstName"), record.get("lastName")) if value) or kind.title()
                details = {key: record.get(key) for key in ("companyName", "emails", "phones")
                           if record.get(key) is not None}
            lines.append(f"- {label} (id {record['id']}): {json.dumps(details, ensure_ascii=False)}")
        if len(records) > 10:
            lines.append(f"… and {len(records) - 10} more records in the trigger output")
        return {"text": f"DoorLoop: {len(records)} new {output['record_type']} record(s):\n" + "\n".join(lines),
                "conversation_key": None}

    async def _poll_new_records(self, config):
        # DoorLoop documents filter_createdAt_from on these four list routes:
        # https://api.doorloop.com/reference/get-tasks (and get-owners/vendors/notes).
        lists = {"on_new_task": DoorLoopListTasks, "on_new_owner": DoorLoopListOwners,
                 "on_new_vendor": DoorLoopListVendors, "on_new_note": DoorLoopListNotes}
        filters = {key: value for key, value in config.model_dump(mode="json", exclude_none=True).items()
                   if key.startswith("filter_")}
        if config.created_since:
            filters["filter_createdAt_from"] = config.created_since.isoformat()
        records = []
        for page in range(1, 11):
            result = await self._execute_operation(lists[config.operation](
                page_number=page, page_size=1000, **filters), poll=True)
            if result.get("status") == "error":
                raise ValueError(result["error"])
            records.extend(result["items"])
            if any(not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]
                   for item in records):
                raise ValueError("DoorLoop poll returned a record without an ID; no baseline was changed")
            if result["total"] > 10000:
                raise ValueError("DoorLoop poll scope exceeds 10,000 records; narrow created since or the resource filter")
            if not result["has_more"]:
                break
        else:
            raise ValueError("DoorLoop poll pagination did not finish; narrow the trigger scope")
        fresh = await self._filter_unseen(records, lambda record: record["id"])
        return {"status": "success", "record_type": config.operation.removeprefix("on_new_"),
                "new_records": fresh, "new_count": len(fresh)}

    async def execute(self, inputs):
        config = self.config.config
        if isinstance(config, _NewRecord):
            return await self._poll_new_records(config)
        return await self._execute_operation(config)

    async def _execute_operation(self, config, *, poll=False):
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a DoorLoop API key")
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for field in ("propertyId", "unitId", "leaseId", "tenantId", "taskId", "ownerId", "vendorId", "leasePaymentId", "noteId"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", values.pop(field))
        if isinstance(config, _Person):
            if "email" in values:
                values["emails"] = [{"type": "Primary", "address": values.pop("email")}]
            if "phone" in values:
                values["phones"] = [{"type": "Mobile", "number": values.pop("phone")}]
        if isinstance(config, DoorLoopCreateNote):
            values["linkedResource"] = {"resourceId": values.pop("resource_id"), "resourceType": values.pop("resource_type")}
            if "tags" in values:
                values["tags"] = list(dict.fromkeys(values["tags"]))
        if method == "GET":
            values = {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"},
                **({"params": values} if method == "GET" else {"json": values} if method != "DELETE" else {}))
        if not 200 <= response.status_code < 300:
            message = "DoorLoop rejected the request"
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = str(error.get("message") or error.get("error") or message)
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code,
                "error": message.replace(credential.api_key, "[redacted]")[:2000]}
        if method == "DELETE":
            return {"status": "success", "deleted": True, "task_id": config.taskId}
        if len(response.content) > 10_000_000:
            raise ValueError("DoorLoop response exceeds the JSON size limit")
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Expected a DoorLoop JSON object")
        if not poll and (body.get("error") or body.get("success") is False):
            raise ValueError("DoorLoop returned an error envelope with a success HTTP status")
        if isinstance(config, _Page):
            if not isinstance(body.get("data"), list) or type(body.get("total")) not in (int, float):
                raise ValueError("DoorLoop page is missing its data array or total")
            has_more = config.page_number * config.page_size < body["total"]
            return {"status": "success", "data": body, "items": body["data"], "total": body["total"],
                "has_more": has_more, "next_page_number": config.page_number + 1 if has_more else None}
        if config.operation == "get_current_user" and not (body.get("loginEmail") or body.get("id")):
            raise ValueError("DoorLoop did not return an account identity")
        return {"status": "success", "data": body}
